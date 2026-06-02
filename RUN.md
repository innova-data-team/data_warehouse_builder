# How to run Data Warehouse Builder

Step-by-step guide for **Streamlit UI**, **FastAPI**, and **diagnostics**.

---

## Table of contents

1. [Choose a mode](#choose-a-mode)
2. [One-time setup](#one-time-setup)
3. [Run Streamlit UI](#run-streamlit-ui)
4. [Run FastAPI](#run-fastapi)
5. [UI workflow](#ui-workflow)
6. [Useful commands](#useful-commands)
7. [Where data is stored](#where-data-is-stored)
8. [Troubleshooting](#troubleshooting)

---

## Choose a mode

| Mode | `.env` setting | MySQL required? | Best for |
|------|----------------|-----------------|----------|
| **File** (default) | `STORAGE_BACKEND=file` | No | Development, Windows, no DB install |
| **MySQL** | `STORAGE_BACKEND=mysql` | Yes | Production, Power BI / ZakaaDash SQL exports |

- Quick file-mode start: [QUICKSTART.md](./QUICKSTART.md)
- MySQL setup: [RUN_MYSQL.md](./RUN_MYSQL.md)

---

## One-time setup

All commands assume you are in the project folder:

```text
data_warehouse_builder/
```

### Install Python dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### Environment file

```powershell
copy .env.example .env
```

Edit `.env` if needed (see `.env.example` for all options).

### Check installation

```powershell
python check_setup.py
```

| Mode | Expected result |
|------|-----------------|
| File | 9/9 checks passed |
| MySQL | 8/8 or 9/9 including MySQL connection |

### Test MySQL (optional)

Only when using `STORAGE_BACKEND=mysql`:

```powershell
python mysql_probe.py
python mysql_probe.py --user YOUR_USER --password YOUR_PASSWORD
```

---

## Run Streamlit UI

### Windows

```bat
run_streamlit.bat
```

Or PowerShell:

```powershell
.\run_streamlit.ps1
```

### Manual (any OS)

```powershell
python -m streamlit run streamlit_app.py ^
  --server.port 8501 ^
  --server.address 127.0.0.1 ^
  --server.headless true ^
  --server.fileWatcherType none
```

```bash
streamlit run streamlit_app.py --server.port 8501
```

### Open in browser

**http://127.0.0.1:8501**

If the browser does not open automatically, paste the URL manually (this avoids some Windows crashes).

### Stop the server

Press **Ctrl+C** in the terminal where Streamlit is running.

---

## Run FastAPI

Optional REST API (same pipeline logic as the UI):

```powershell
.\.venv\Scripts\activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

- API docs: http://127.0.0.1:8080/docs
- Health: http://127.0.0.1:8080/docs (OpenAPI)

You can run **Streamlit and API together** on ports **8501** and **8080**.

---

## UI workflow

### Sidebar

- **Active batch** — select or create a batch
- **Refresh** — reload batch list after upload
- **New batch** — clear selection for a fresh upload
- Progress chip for the current pipeline stage

### Tabs

| Tab | What to do |
|-----|------------|
| **Upload** | Add CSV, Excel, JSON; creates a new batch (or append) |
| **Pipeline** | Task progress table; **Full run** or per-stage buttons; **View data** previews |
| **Relationships** | Approve / reject suggested joins before Gold |
| **Reports** | Quality issues, data dictionary, lineage |
| **Files** | List all files; download Parquet/CSV/ZIP (same extension as on disk) |
| **Exports** | CSV copies; Power BI / ZakaaDash when MySQL mode |

### Recommended order

```text
Upload → Full run → View data → Relationships (approve) → Gold → Files (download)
```

### Task progress states

| Status | Meaning |
|--------|---------|
| Pending | Not started yet |
| Running | Step executing now |
| Done | Step finished |
| Failed | Error — see message in table |

---

## Useful commands

| Command | Purpose |
|---------|---------|
| `python check_setup.py` | Verify Python packages and storage |
| `python mysql_probe.py` | Test MySQL credentials and driver |
| `run_streamlit.bat` | Start UI on Windows |
| `pytest tests/` | Run unit tests |

---

## Where data is stored

### File mode (`STORAGE_BACKEND=file`)

```text
storage/
  raw/{batch_id}/              # Original uploads
  batches/{batch_id}/
    batch.json
    files.json
    pipeline_progress.json     # Task tracker (done/pending)
    bronze/*.parquet
    silver/*.parquet
    gold/*.parquet
    profiles/
    quality_issues.json
    relationships/
  exports/{batch_id}/
    parquet/                   # Optional Parquet bundle
    csv/                       # Optional CSV copies
sql/generated/{batch_id}/      # Generated SQL scripts
```

### MySQL mode

Same logical layers in databases: `dw_metadata`, `dw_bronze`, `dw_silver`, `dw_gold`.

---

## Troubleshooting

### Streamlit crashes on Windows (exit code -1073741819)

1. Use `run_streamlit.bat` (headless + manual browser).
2. Upgrade Streamlit: `pip install streamlit==1.45.1`
3. Open http://127.0.0.1:8501 manually in Chrome or Edge.

### New batch not in sidebar after upload

Click **Refresh** in the sidebar, or upload again (auto-rerun should select the new batch).

### `check_setup.py` MySQL fails

- Use file mode: `STORAGE_BACKEND=file` in `.env`
- Or follow [RUN_MYSQL.md](./RUN_MYSQL.md)

### Full run fails on one step

Check **Task progress** for the failed step, fix data or permissions, then run that stage alone (**Bronze**, **Silver**, etc.).

### Cannot preview data

Table preview needs **file mode** and completed Bronze/Silver/Gold steps. Use **View data** on the Pipeline tab or **Files** tab.

---

## Docker (optional)

```powershell
copy .env.example .env
docker compose up --build
```

- Streamlit: http://localhost:8501
- API: http://localhost:8080/docs
- MySQL: localhost:3306

For local development without Docker, prefer **file mode** and `run_streamlit.bat`.
