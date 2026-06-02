# Data Warehouse Builder — Implementation Plan

> A production-grade, Arabic-aware, file-to-MySQL data warehouse system with a
> **human-in-the-loop relationship approval step** between Silver and Gold,
> producing Power BI and ZakaaDash-ready outputs.

This document is the architectural source of truth for the project. It covers
the full plan in 20 sections corresponding to the original brief.

---

## 1. Final Architecture

```text
                ┌─────────────────────────┐
                │  Client (UI / Postman)  │
                └────────────┬────────────┘
                             │  HTTP
                             ▼
              ┌─────────────────────────────┐
              │      FastAPI Application    │
              │  (app/main.py + routers)    │
              └──┬──────────┬──────────┬────┘
                 │          │          │
                 ▼          ▼          ▼
        ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
        │   Services   │ │   Schemas    │ │    Utils     │
        │  (pipelines) │ │  (Pydantic)  │ │ (helpers)    │
        └──┬───────────┘ └──────────────┘ └──────────────┘
           │
           ▼
   ┌──────────────────────────────────────────────────┐
   │                MySQL (4 schemas)                 │
   │  dw_metadata │ dw_bronze │ dw_silver │ dw_gold   │
   └──────────────────────────────────────────────────┘
           │
           ▼
   ┌──────────────────────────────────────────────────┐
   │  Filesystem: storage/{raw, cache, exports, reports}│
   │  + sql/generated/{bronze, silver, gold, views, …} │
   └──────────────────────────────────────────────────┘
```

**Layer responsibilities**

| Layer       | Storage                          | Purpose                                                                 |
| ----------- | -------------------------------- | ----------------------------------------------------------------------- |
| Raw         | `storage/raw/{batch_id}/`        | Untouched original files + hash + manifest                              |
| Bronze      | MySQL schema `dw_bronze`         | 1:1 ingestion, preserve raw values, add lineage columns                 |
| Profiling   | MySQL schema `dw_metadata`       | Table/column profiles, semantic-type detection, quality issues          |
| Silver      | MySQL schema `dw_silver`         | Cleaned, typed, deduplicated, Arabic-normalized data                    |
| Suggestions | MySQL schema `dw_metadata`       | Auto-detected relationships + scoring + user approval state             |
| Gold        | MySQL schema `dw_gold`           | Star schema (facts + dims), analytical views, KPI views                 |
| Exports     | `storage/exports/{batch_id}/`    | Power BI package, ZakaaDash package, final CSV/XLSX, SQL, reports       |

**Design principles**

- **Idempotent batches** — every upload becomes a `batch_id`; all artifacts are namespaced by it.
- **No destructive cleaning** — Bronze always retains the raw value; Silver records the original alongside the cleaned value where transformation is risky.
- **Human-in-the-loop FKs** — Gold is *blocked* until relationships are approved.
- **Lineage-first** — every Silver/Gold row links back to its Bronze row, file, sheet, and source row number.
- **Arabic-first** — the entire stack assumes mixed Arabic/English data and stores both original and safe technical identifiers.

---

## 2. Folder Structure

Matches the brief exactly (see `README.md` for the full tree). Top-level:

```text
data_warehouse_builder/
├── app/
│   ├── main.py
│   ├── api/         # FastAPI routers (one per resource)
│   ├── core/        # config, db, logging, exceptions
│   ├── services/    # one service per pipeline stage
│   ├── models/      # SQLAlchemy ORM (metadata DB)
│   ├── schemas/     # Pydantic request/response models
│   └── utils/       # pure helpers (Arabic, types, sql, …)
├── storage/{raw,cache,exports,reports}/
├── sql/generated/{bronze,silver,gold,views,indexes,metadata}/
├── tests/
├── requirements.txt
├── README.md
├── PLAN.md          # this file
└── .env.example
```

---

## 3. Database Design

Four logical MySQL schemas, all `utf8mb4 / utf8mb4_unicode_ci`:

```sql
CREATE DATABASE IF NOT EXISTS dw_metadata
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS dw_bronze
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS dw_silver
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS dw_gold
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

Connection management lives in `app/core/database.py`, which exposes one
SQLAlchemy `Engine` per schema (`metadata_engine`, `bronze_engine`, …) plus a
session factory `get_metadata_session()`.

---

## 4. Metadata Tables (in `dw_metadata`)

| Table                       | Purpose                                                      |
| --------------------------- | ------------------------------------------------------------ |
| `batches`                   | One row per upload session                                   |
| `uploaded_files`            | One row per physical file (with hash, encoding, etc.)        |
| `bronze_tables`             | Registry of created Bronze tables                            |
| `silver_tables`             | Registry of created Silver tables                            |
| `gold_tables`               | Registry of Gold facts/dims/views                            |
| `table_profiles`            | Per-table profiling output                                   |
| `column_profiles`           | Per-column profiling + semantic type                         |
| `quality_issues`            | One row per detected issue (33 check types)                  |
| `relationship_suggestions`  | Auto-detected candidate relationships (with scores)          |
| `approved_relationships`    | User-approved/edited relationships consumed by Gold builder  |
| `export_jobs`               | Tracks Power BI / ZakaaDash / final export packaging         |
| `generated_sql_files`       | Index of all `.sql` files produced per batch                 |

Full DDL is in `sql/generated/metadata/example_metadata_tables.sql` and the
ORM definitions in `app/models/`.

---

## 5. Bronze / Silver / Gold Strategy

### Bronze
- One table per (file, sheet) — `bronze_{safe_name}` or `bronze_{file}_{sheet}`.
- Every column stored as `TEXT` / `LONGTEXT` to prevent loss.
- Mandatory lineage columns:
  `_bronze_id`, `_batch_id`, `_source_file_id`, `_source_file_name`,
  `_source_sheet_name`, `_source_row_number`, `_raw_record_hash`,
  `_ingested_at`.
- Original → safe column mapping persisted in `column_profiles`.

### Silver
- One Silver table per Bronze table: `silver_{base}`.
- Typed columns based on profiler output + semantic detection.
- Arabic text normalized, dates parsed, percentages converted to floats, etc.
- Cleaning is **rule-based and logged**: each transformation records before/after value categories.
- Lineage columns:
  `_silver_id`, `_batch_id`, `_bronze_id`, `_source_file_id`,
  `_source_row_number`, `_clean_record_hash`, `_quality_score`,
  `_cleaning_status`, `_cleaned_at`.

### Gold
- Built **only** from Silver + **approved** relationships.
- Produces:
  - `gold_dim_*` (dimension tables, surrogate keys + natural keys)
  - `gold_fact_*` (fact tables with FK columns to dims)
  - `gold_v_*` (joined analytical views, KPI views, flat views)
- Aggregation safety: parent-table measures use distinct-by-PK aggregation to
  avoid duplication after one-to-many joins.

---

## 6. Data Quality Rules (33 checks)

Implemented as discrete check functions inside
`services/data_quality_service.py`. Each returns a `QualityIssue` with
`severity ∈ {Critical, High, Medium, Low, Info}`, `auto_fix_available`, and
`suggested_fix`. The full list (numbered as in the brief) is wired in
`DataQualityService.CHECKS`.

Notable, non-obvious checks:

- **Mixed types** — `type_detection.detect_column_type()` reports the
  distribution of values per detected type; if no type ≥ 95 %, the column
  is flagged.
- **Broken Arabic encoding** — detected when the column contains substrings
  matching mojibake patterns (e.g., `Ø§Ø`) or when Windows-1256 round-trip
  would yield more valid Arabic letters.
- **Many-to-many join risk** and **measure duplication risk** — produced
  during relationship detection, not column profiling, but stored in the
  same `quality_issues` table for unified reporting.

---

## 7. Arabic Normalization Strategy

Implemented in `app/utils/arabic_text_normalization.py`. Pipeline order:

1. Unicode `NFKC` normalization
2. Strip BOM / zero-width characters
3. Remove tashkeel (`\u064B-\u065F`, `\u0670`)
4. Remove tatweel (`\u0640`)
5. Map letter variants:
   `أإآ → ا`, `ى → ي` (configurable), optional `ة → ه`
6. Collapse Arabic-Indic / Persian digits to ASCII digits
7. Normalize Arabic punctuation (`،;؛?؟`)
8. Trim + collapse multiple spaces

Column-name handling:
- Original Arabic name stored in `column_profiles.original_name`.
- Safe ASCII identifier produced by `column_utils.safe_identifier()`:
  - normalize → Unidecode → snake_case → strip MySQL reserved words
  - guaranteed length ≤ 64 chars (MySQL identifier limit).
- Stable hash suffix added when collision occurs (`name__a1b2`).

---

## 8. Relationship Detection Algorithm

Implemented in `app/services/relationship_detector_service.py`. For each
column pair `(A.col_a, B.col_b)` across all Silver tables, compute:

| Signal                          | Weight |
| ------------------------------- | -----: |
| Safe-name similarity (Jaro-W.)  |   0.20 |
| Original-name semantic match    |   0.10 |
| Data-type compatibility (0/1)   |   0.15 |
| Value overlap ratio             |   0.30 |
| Cardinality compatibility       |   0.10 |
| PK/uniqueness on one side       |   0.10 |
| Business-name patterns          |   0.05 |

`confidence_score ∈ [0, 1]` is a weighted sum, clamped. A pair is emitted as
a suggestion when `confidence_score ≥ RELATIONSHIP_MIN_CONFIDENCE` *and*
`value_overlap_score ≥ RELATIONSHIP_VALUE_OVERLAP_THRESHOLD`.

Suggested relationship type inferred from cardinality:

- both sides unique → `one_to_one`
- right side unique, left side has duplicates → `many_to_one`
- left side unique, right side has duplicates → `one_to_many`
- both sides non-unique → `many_to_many` (flagged High risk)

Risks attached:
- `MEASURE_DUPLICATION_RISK` for one-to-many joins on a fact-like left side
- `M2M_RISK` for many-to-many
- `WEAK_OVERLAP` when overlap < 0.7 but ≥ threshold
- `HIGH_NULL_FK` if FK side null % > 30
- `TYPE_COERCION` if numeric ↔ string match required normalization

---

## 9. Relationship Approval Workflow

```
detect ──► relationship_suggestions (status='suggested')
              │
   user reviews via API
              │
   ┌──────────┼──────────┬──────────┐
   ▼          ▼          ▼          ▼
approve   reject     edit       (skip)
   │          │          │          │
   ▼          ▼          ▼          ▼
   └──► approved_relationships ◄────┘
                      │
                Gold builder
```

APIs (`api/relationship_routes.py` + `api/approval_routes.py`):
- `GET /pipeline/{batch_id}/relationships/suggestions`
- `POST /pipeline/{batch_id}/relationships/{id}/approve`
- `POST /pipeline/{batch_id}/relationships/{id}/reject`
- `PUT  /pipeline/{batch_id}/relationships/{id}/edit`

Gold generation **refuses to run** if `count(approved_relationships) == 0`
and more than one Silver table exists.

---

## 10. Gold Generation Strategy

Driven by `gold_service.GoldBuilder`:

1. Load Silver inventory + approved relationships.
2. Classify each Silver table as `fact` / `dim` / `bridge` / `flat` using:
   - row count, presence of dates, presence of measures, PK uniqueness,
   - in-degree / out-degree in the approved relationship graph.
3. Build dimension tables: select descriptive columns, add surrogate key
   (`{dim}_sk BIGINT AUTO_INCREMENT`), keep natural key.
4. Build fact tables: join Silver fact to each related dim to fetch the
   surrogate key, drop natural-key columns that are now redundant.
5. Build analytical views:
   - `gold_v_{fact}_with_dims` — fully joined flat view
   - `gold_v_kpi_summary` — pre-aggregated KPIs (sum, avg, count, distinct)
   - `gold_v_{business_area}_analysis` — domain views derived from objectives
6. Create indexes on every FK and on every column flagged as a filter
   candidate by the profiler.

Anti-duplication rules:
- Measures from the *parent* side of a 1:N relation are projected via
  `SELECT ... GROUP BY pk` before joining.
- All join paths are reduced to a spanning tree (BFS) to avoid fan-traps.

---

## 11. Power BI Output Design

Folder: `storage/exports/{batch_id}/powerbi/`

| File                          | Content                                                    |
| ----------------------------- | ---------------------------------------------------------- |
| `powerbi_data_dictionary.xlsx`| Sheet per table — column, type, Arabic name, description   |
| `powerbi_relationships.xlsx`  | from-table, from-col, to-table, to-col, cardinality, dir   |
| `suggested_dax_measures.md`   | DAX snippets per fact table                                |
| `mysql_connection_notes.md`   | How to connect Power BI Desktop to `dw_gold`               |

DAX templates auto-generated per detected measure:

```dax
Total {Measure} = SUM ( {Fact}[{measure_col}] )
Distinct {Entity} = DISTINCTCOUNT ( {Fact}[{entity_id_col}] )
{Measure} YoY % =
    DIVIDE (
        [Total {Measure}] - CALCULATE ( [Total {Measure}], SAMEPERIODLASTYEAR ( dim_date[date] ) ),
        CALCULATE ( [Total {Measure}], SAMEPERIODLASTYEAR ( dim_date[date] ) )
    )
```

---

## 12. ZakaaDash Output Design

Folder: `storage/exports/{batch_id}/zakaadash/`

| File                                  | Content                                          |
| ------------------------------------- | ------------------------------------------------ |
| `zakaadash_views.sql`                 | Flat + KPI views ready for direct binding        |
| `dashboard_objectives.json`           | Per-business-area objectives                     |
| `chart_recommendations.json`          | Suggested chart specs (see schema below)         |
| `arabic_english_data_dictionary.xlsx` | Bilingual dictionary                             |

`chart_recommendations.json` schema:

```jsonc
{
  "charts": [
    {
      "chart_id": "kpi_total_revenue",
      "chart_title_ar": "إجمالي الإيرادات",
      "chart_title_en": "Total Revenue",
      "chart_type": "kpi_card",
      "view": "gold_v_kpi_summary",
      "dimension_columns": [],
      "measure_columns": ["total_revenue"],
      "aggregation": "sum",
      "filter_columns": ["fiscal_year"],
      "drilldown_columns": ["region", "branch"],
      "business_question_en": "What is the total revenue this year?",
      "business_question_ar": "ما هو إجمالي الإيرادات هذا العام؟"
    }
  ]
}
```

---

## 13. API Design

All endpoints return `application/json` (Pydantic models) and use the
standard error envelope from `core/exceptions.py`.

Resource layout (mirrors the brief):

```
POST   /upload/files
POST   /pipeline/{batch_id}/run
GET    /pipeline/{batch_id}/status
POST   /pipeline/{batch_id}/bronze/run
GET    /pipeline/{batch_id}/bronze/tables
POST   /pipeline/{batch_id}/silver/run
GET    /pipeline/{batch_id}/silver/tables
POST   /pipeline/{batch_id}/relationships/detect
GET    /pipeline/{batch_id}/relationships/suggestions
POST   /pipeline/{batch_id}/relationships/{id}/approve
POST   /pipeline/{batch_id}/relationships/{id}/reject
PUT    /pipeline/{batch_id}/relationships/{id}/edit
POST   /pipeline/{batch_id}/gold/run
GET    /pipeline/{batch_id}/gold/tables
GET    /pipeline/{batch_id}/gold/views
GET    /reports/{batch_id}/quality
GET    /reports/{batch_id}/relationships
GET    /reports/{batch_id}/data-dictionary
GET    /reports/{batch_id}/lineage
GET    /exports/{batch_id}/powerbi
GET    /exports/{batch_id}/zakaadash
GET    /exports/{batch_id}/final-files
GET    /exports/{batch_id}/sql
```

---

## 14. SQL Generation Strategy

The `sql_generator_service` writes one `.sql` file per artifact under
`sql/generated/{batch_id}/...`. The generator always:

- wraps every identifier in backticks
- emits `CREATE DATABASE` with `utf8mb4 / utf8mb4_unicode_ci`
- escapes reserved words via `sql_utils.is_reserved_word()`
- includes a header comment with `batch_id`, source file, generation time
- emits `CREATE INDEX` statements after table DDL
- emits `LOAD DATA LOCAL INFILE` (preferred) or `INSERT` batches for Bronze
- emits `INSERT … SELECT` for Bronze→Silver and Silver→Gold transforms

FK constraints are **suggested** (commented `-- ADD CONSTRAINT`) but only
emitted as enforced `ALTER TABLE … ADD CONSTRAINT` when the user calls
the corresponding "enforce" endpoint. Default is non-enforced because data
quality is unknown at first ingest.

---

## 15. Edge Case Handling

Each edge case in the brief is mapped to an implementation point:

| Edge case                         | Handler                                                     |
| --------------------------------- | ----------------------------------------------------------- |
| Arabic / duplicate / empty cols   | `column_utils.normalize_headers()`                          |
| Excel empty-top-rows              | `file_reader_service._detect_header_row()`                  |
| Wrong CSV encoding                | `file_reader_service._detect_encoding()` (chardet + heuristics) |
| CSV delimiter (`,;\t|`)           | `csv.Sniffer` + custom fallback in `file_reader_service`    |
| Nested JSON                       | `json_utils.flatten_json()`                                 |
| `5% / ٥٪ / 0.05`                  | `number_utils.parse_percentage()`                           |
| Multi-format dates                | `date_utils.parse_date()` (dateutil + custom Arabic month)  |
| Null-like tokens                  | `validation_utils.NULL_TOKENS`                              |
| Boolean variants (نعم/لا, 1/0…)   | `validation_utils.parse_boolean()`                          |
| Many-to-many joins                | `relationship_detector_service` flags + Gold refuses        |
| MySQL reserved words & long names | `sql_utils.safe_table_name()` (≤ 64, `_t` suffix)           |

---

## 16. Step-by-Step Implementation Plan

(See README phases 1-8 — exactly the order in the brief.)

1. **Phase 1** — Project scaffold, config, DB connection, metadata DDL, upload + raw storage.
2. **Phase 2** — `file_reader_service`, Bronze table creation + load + SQL.
3. **Phase 3** — Profiler + data quality engine + reports.
4. **Phase 4** — Cleaner + Arabic normalization + Silver build + load.
5. **Phase 5** — Relationship detector + scoring + suggestion / approval APIs.
6. **Phase 6** — Gold builder, fact/dim detection, views.
7. **Phase 7** — SQL generator finalize, Power BI + ZakaaDash export.
8. **Phase 8** — Tests, README polish, end-to-end example.

Each phase has its own service module(s), router(s), and test file. Phases
can be developed in parallel after Phase 1 is done because the contracts
(Pydantic schemas + ORM models) are stable.

---

## 17. Initial Code Scaffold

Delivered in this commit:

- `app/main.py` — FastAPI app, lifespan, router wiring
- `app/core/{config,database,logging,exceptions}.py`
- `app/utils/` — all 9 helper modules (Arabic, types, sql, …)
- `app/schemas/` — all 6 Pydantic modules
- `app/models/` — all 11 SQLAlchemy models
- `app/services/` — all 14 service modules (production logic for the
  critical ones, well-typed contracts for the rest)
- `app/api/` — all 6 routers
- `tests/` — pytest skeletons for every critical service
- `sql/generated/` — example DDL for each layer

---

## 18. requirements.txt

See `requirements.txt`. Pins are conservative and tested with Python 3.11/3.12.

---

## 19. README Draft

See `README.md` for setup, run, and end-to-end usage walkthrough.

---

## 20. Example MySQL SQL Output

See `sql/generated/`:

- `metadata/example_metadata_tables.sql` — full DDL for the 12 metadata tables
- `bronze/example_bronze_table.sql`      — sample bronze ingest table
- `silver/example_silver_table.sql`      — silver transform + INSERT SELECT
- `gold/example_gold_star.sql`           — fact + dim + indexes
- `views/example_gold_view.sql`          — analytical + KPI view
- `indexes/example_indexes.sql`          — indexing strategy
- `create_databases.sql`                  — the four schemas

These files are committed and runnable against a fresh MySQL 8 instance.
