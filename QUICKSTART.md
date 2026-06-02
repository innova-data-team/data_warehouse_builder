# Quick start (file mode — no MySQL)

Get the UI running in a few minutes. Data is stored as **Parquet + JSON** under `storage/`.

## 1. Prerequisites

- Python **3.11** or **3.12**
- Windows, Linux, or macOS

## 2. Install

```powershell
cd data_warehouse_builder

python -m venv .venv
.\.venv\Scripts\activate

pip install -r requirements.txt
```

```bash
# Linux / macOS
cd data_warehouse_builder
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Configure

```powershell
copy .env.example .env
```

Ensure `.env` contains:

```ini
STORAGE_BACKEND=file
```

No MySQL setup is required for this path.

## 4. Verify setup

```powershell
python check_setup.py
```

Expect **9/9** checks passed (MySQL check is skipped in file mode).

## 5. Run the UI

**Windows (recommended):**

```bat
run_streamlit.bat
```

**Or manually:**

```powershell
python -m streamlit run streamlit_app.py --server.port 8501
```

Open: **http://127.0.0.1:8501**

## 6. First pipeline

1. **Upload** — add CSV / Excel / JSON files → **Upload & start**
2. **Pipeline** — click **Full run** (Bronze → Silver → Relationships)
3. Watch **Task progress** (Done / Pending / Running)
4. **View data** — preview Raw / Bronze / Silver tables
5. **Relationships** — approve links if you have multiple tables
6. **Pipeline** — **Gold** (after approval if needed)
7. **Files** — download Parquet or ZIP bundles

## Next steps

- Full details: [RUN.md](./RUN.md)
- MySQL mode: [RUN_MYSQL.md](./RUN_MYSQL.md)
- Architecture: [PLAN.md](./PLAN.md)
