# Data Warehouse Builder

> Intelligent **file → warehouse → analytics** pipeline.
> Accepts CSV / Excel / JSON, builds **Bronze / Silver / Gold** layers,
> detects data quality issues, suggests relationships, lets a human
> approve them, then produces **Power BI** and **ZakaaDash**-ready outputs.
> First-class support for **Arabic** and mixed Arabic/English data.

## Run guides (start here)

| Document | Description |
|----------|-------------|
| **[QUICKSTART.md](./QUICKSTART.md)** | Fastest path — file mode, no MySQL |
| **[RUN.md](./RUN.md)** | Full run instructions (UI, API, workflow, storage) |
| **[RUN_MYSQL.md](./RUN_MYSQL.md)** | MySQL setup, grants, connection probe |

**Windows UI:** double-click `run_streamlit.bat` → http://127.0.0.1:8501

---

## Table of Contents

1. [Features](#features)
2. [Architecture](#architecture)
3. [Folder Structure](#folder-structure)
4. [Requirements](#requirements)
5. [Setup](#setup)
6. [Running the API](#running-the-api)
7. [End-to-End Walkthrough](#end-to-end-walkthrough)
8. [Approval Workflow](#approval-workflow)
9. [Outputs Produced](#outputs-produced)
10. [Project Phases](#project-phases)
11. [Testing](#testing)
12. [Troubleshooting](#troubleshooting)

---

## Features

- **Multi-format ingest** — CSV (auto-detect delimiter and encoding), Excel
  (multi-sheet, Arabic sheet names, empty top rows), JSON (nested + JSONL).
- **Four MySQL schemas** — `dw_metadata`, `dw_bronze`, `dw_silver`, `dw_gold`,
  all `utf8mb4 / utf8mb4_unicode_ci`.
- **Bronze layer** — lossless raw ingest with full lineage columns.
- **Profiler** — table + column profiles, semantic-type detection, sample
  values, Arabic / English distribution.
- **Data quality engine** — 33 checks across severities (Critical → Info).
- **Arabic normalization** — alef/yaa/ta-marbuta variants, tashkeel,
  Arabic-Indic digits, Arabic punctuation, mojibake detection.
- **Silver layer** — typed, normalized, deduplicated, fully logged.
- **Relationship detector** — score-based suggestions across all Silver
  tables; risks for many-to-many and measure-duplication.
- **Human-in-the-loop approval** — Gold is blocked until relationships are
  approved through the API.
- **Gold layer** — fact / dimension star schema, KPI views, flat views,
  duplicate-measure-safe joins.
- **Exports** — Power BI and ZakaaDash packages, final CSV/XLSX, full SQL,
  data dictionary, lineage report.

---

## Architecture

See [`PLAN.md`](./PLAN.md) for the full architectural plan (20 sections).
Short version:

```
Files ──► Upload API ──► Raw storage ──► Bronze (MySQL)
                                          │
                                          ▼
                                   Profiler + DQ Engine ──► quality_issues
                                          │
                                          ▼
                                   Silver (MySQL, cleaned + typed)
                                          │
                                          ▼
                          Relationship Detector ──► suggestions
                                          │
                                  ┌───────┴────────┐
                                  ▼                ▼
                            user approves     user rejects/edits
                                  │
                                  ▼
                         Gold (MySQL star schema)
                                  │
                                  ▼
                Power BI + ZakaaDash + SQL + reports
```

---

## Folder Structure

```text
data_warehouse_builder/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── upload_routes.py
│   │   ├── pipeline_routes.py
│   │   ├── relationship_routes.py
│   │   ├── approval_routes.py
│   │   ├── export_routes.py
│   │   └── report_routes.py
│   ├── core/
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── logging.py
│   │   └── exceptions.py
│   ├── services/
│   │   ├── file_reader_service.py
│   │   ├── upload_service.py
│   │   ├── bronze_service.py
│   │   ├── profiler_service.py
│   │   ├── data_quality_service.py
│   │   ├── cleaner_service.py
│   │   ├── silver_service.py
│   │   ├── relationship_detector_service.py
│   │   ├── relationship_approval_service.py
│   │   ├── gold_service.py
│   │   ├── sql_generator_service.py
│   │   ├── export_service.py
│   │   ├── powerbi_export_service.py
│   │   └── zakaadash_export_service.py
│   ├── models/   # SQLAlchemy ORM (metadata DB)
│   ├── schemas/  # Pydantic request/response models
│   └── utils/    # arabic_text_normalization, type_detection, ...
├── storage/{raw,cache,exports,reports}/
├── sql/generated/{metadata,bronze,silver,gold,views,indexes}/
├── tests/
├── streamlit_app.py          # Web UI (Streamlit)
├── docker-compose.yml        # MySQL + API + Streamlit
├── Dockerfile
├── run_streamlit.bat / .ps1
├── requirements.txt
├── README.md
├── QUICKSTART.md             # Fast start (file mode)
├── RUN.md                    # How to run UI + API
├── RUN_MYSQL.md              # MySQL setup
├── PLAN.md
└── .env.example
```

---

## Requirements

- Python 3.11 or 3.12
- MySQL 8.0 (or compatible — MariaDB 10.6+ may work but is untested)
- ~2 GB RAM for the default profiler sample size (`PROFILER_SAMPLE_ROWS=100000`)

---

## Setup

```bash
# 1. Clone and enter the project
cd data_warehouse_builder

# 2. Create a virtual env
python -m venv .venv
.\.venv\Scripts\activate          # Windows
# source .venv/bin/activate       # Linux / macOS

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy environment template and edit credentials
copy .env.example .env             # Windows
# cp .env.example .env             # Linux / macOS

# 5. Create the MySQL databases (one time)
mysql -u root -p < sql/generated/create_databases.sql

# 6. Create the metadata tables (one time)
mysql -u root -p dw_metadata < sql/generated/metadata/example_metadata_tables.sql
```

---

## Running the API

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

Open the interactive docs: <http://localhost:8080/docs>

---

## Streamlit UI (recommended)

See **[RUN.md](./RUN.md)** and **[QUICKSTART.md](./QUICKSTART.md)** for full steps.

```bash
cd data_warehouse_builder
pip install -r requirements.txt
python check_setup.py
streamlit run streamlit_app.py
```

Windows:

```bat
run_streamlit.bat
```

Open: <http://127.0.0.1:8501>

Default: **`STORAGE_BACKEND=file`** (Parquet on disk, no MySQL).

### UI tabs

| Tab | Purpose |
| --- | ------- |
| **Upload** | Upload CSV / Excel / JSON; task progress after upload |
| **Pipeline** | Task tracker (done/pending/running); full run; **View data** previews |
| **Relationships** | Review, approve, or reject suggested joins |
| **Reports** | Quality issues, data dictionary, lineage |
| **Files** | All batch files; download Parquet/ZIP (original extensions) |
| **Exports** | CSV copies; Power BI / ZakaaDash (MySQL mode) |

### Docker (MySQL + API + Streamlit)

```bash
cd data_warehouse_builder
copy .env.example .env
docker compose up --build
```

- Streamlit UI: <http://localhost:8501>
- FastAPI docs: <http://localhost:8080/docs>
- MySQL: `localhost:3306` (user `dw_user` / password `change_me`)

---

## End-to-End Walkthrough

### 1. Upload files

```bash
curl -X POST http://localhost:8080/upload/files \
  -F "files=@./samples/hospitals.xlsx" \
  -F "files=@./samples/patients_ar.csv"
# → { "batch_id": "b_2026_05_24_001", "files": [...] }
```

### 2. Run the pipeline up to the approval step

```bash
curl -X POST http://localhost:8080/pipeline/b_2026_05_24_001/run
```

This runs Bronze ingest → Profiler + DQ → Silver build → Relationship
detection, then **stops** and returns the list of suggested relationships.

### 3. Review and approve relationships

```bash
curl http://localhost:8080/pipeline/b_2026_05_24_001/relationships/suggestions
curl -X POST http://localhost:8080/pipeline/b_2026_05_24_001/relationships/42/approve
curl -X POST http://localhost:8080/pipeline/b_2026_05_24_001/relationships/77/reject
```

### 4. Build Gold + exports

```bash
curl -X POST http://localhost:8080/pipeline/b_2026_05_24_001/gold/run
curl http://localhost:8080/exports/b_2026_05_24_001/powerbi
curl http://localhost:8080/exports/b_2026_05_24_001/zakaadash
```

All artifacts land in `storage/exports/{batch_id}/`.

---

## Approval Workflow

Gold generation is blocked unless at least one relationship has been
approved (when there are 2+ Silver tables). This is intentional:
**bad relationships make worse dashboards**.

| Action  | Endpoint                                                              |
| ------- | --------------------------------------------------------------------- |
| List    | `GET  /pipeline/{batch_id}/relationships/suggestions`                 |
| Approve | `POST /pipeline/{batch_id}/relationships/{id}/approve`                |
| Reject  | `POST /pipeline/{batch_id}/relationships/{id}/reject`                 |
| Edit    | `PUT  /pipeline/{batch_id}/relationships/{id}/edit` (body = override) |

---

## Outputs Produced (per batch)

```text
storage/exports/{batch_id}/
├── final_cleaned_files/
│   ├── gold_fact_*.csv
│   ├── gold_dim_*.csv
│   └── gold_analysis_view.xlsx
├── reports/
│   ├── data_quality_report.xlsx
│   ├── relationship_report.xlsx
│   ├── data_dictionary.xlsx
│   └── lineage_report.json
├── sql/
│   ├── create_databases.sql
│   ├── create_bronze_tables.sql
│   ├── create_silver_tables.sql
│   ├── create_gold_tables.sql
│   ├── create_gold_views.sql
│   └── create_indexes.sql
├── powerbi/
│   ├── powerbi_data_dictionary.xlsx
│   ├── powerbi_relationships.xlsx
│   ├── suggested_dax_measures.md
│   └── mysql_connection_notes.md
└── zakaadash/
    ├── zakaadash_views.sql
    ├── dashboard_objectives.json
    ├── chart_recommendations.json
    └── arabic_english_data_dictionary.xlsx
```

---

## Project Phases

The codebase is built in 8 phases, exactly as in the brief.
See [`PLAN.md` §16](./PLAN.md#16-step-by-step-implementation-plan) for the
phase-by-phase plan.

---

## Testing

```bash
pytest -q
```

Critical tests:

```bash
pytest tests/test_file_reader.py             # multi-format ingest
pytest tests/test_profiler_service.py        # semantic types + Arabic %
pytest tests/test_cleaner_service.py         # Arabic normalization
pytest tests/test_relationship_detector.py   # scoring + risks
pytest tests/test_sql_generator.py           # safe identifiers + DDL
```

---

## Troubleshooting

| Symptom                                          | Likely cause / fix                                                                   |
| ------------------------------------------------ | ------------------------------------------------------------------------------------ |
| `1366 Incorrect string value` on insert          | The target schema is not `utf8mb4`. Re-run `create_databases.sql`.                   |
| Arabic shows as `Ø§Ø¹` in Bronze                 | Source file was `windows-1256` — the reader will retry; if not, set `MYSQL_CHARSET`. |
| Gold endpoint returns `422` "no approved rels"   | Approve at least one relationship via the approval API.                              |
| Profiler is slow on huge files                   | Lower `PROFILER_SAMPLE_ROWS` in `.env`.                                              |
| `Identifier too long`                            | Caused by very long sheet/column names — fixed by `sql_utils.safe_table_name`.       |
