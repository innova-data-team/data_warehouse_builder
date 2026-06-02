"""Silver layer builder.

Given a Bronze table + its profile, this service produces a Silver table
in MySQL with typed, normalized, deduplicated data, plus lineage columns.
The actual per-column cleaning is delegated to
:mod:`app.services.cleaner_service`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable

import polars as pl
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import bronze_engine, silver_engine
from app.core.logging import get_logger
from app.models import BronzeTable, SilverTable
from app.services.cleaner_service import CleaningStats, clean_column
from app.services.profiler_service import TableProfileResult
from app.utils.hash_utils import hash_record
from app.utils.sql_utils import (
    ddl_charset_clause,
    quote_identifier,
    safe_table_name,
)

_log = get_logger(__name__)

SILVER_META_COLUMNS = (
    "_silver_id", "_batch_id", "_bronze_id", "_source_file_id",
    "_source_row_number", "_clean_record_hash", "_quality_score",
    "_cleaning_status", "_cleaned_at",
)


# ---------------------------------------------------------------------------
def _physical_to_mysql(physical_type: str, sample_lengths: Iterable[int]) -> str:
    max_len = max(sample_lengths, default=0)
    match physical_type:
        case "integer":
            return "BIGINT"
        case "float":
            return "DOUBLE"
        case "decimal":
            return "DECIMAL(20, 6)"
        case "boolean":
            return "TINYINT(1)"
        case "date":
            return "DATE"
        case "datetime":
            return "DATETIME"
        case "text":
            return "LONGTEXT"
        case _:
            if max_len > 1024:
                return "TEXT"
            return f"VARCHAR({max(64, min(1024, (max_len or 64) * 2))})"


class SilverService:
    """Materializes a Silver table for each Bronze input."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.bronze: Engine = bronze_engine()
        self.silver: Engine = silver_engine()

    # ------------------------------------------------------------------
    def build_from_bronze(
        self,
        *,
        batch_id: str,
        bronze: BronzeTable,
        profile: TableProfileResult,
    ) -> SilverTable:
        # Load Bronze frame as strings
        with self.bronze.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT * FROM " + quote_identifier(bronze.table_name)
                    + " WHERE `_batch_id` = :bid"
                ),
                {"bid": batch_id},
            ).mappings().all()

        if not rows:
            _log.info("Silver build skipped (empty Bronze): %s", bronze.table_name)
            silver = SilverTable(
                batch_id=batch_id, bronze_table_id=bronze.id,
                table_name=safe_table_name(f"silver_{bronze.table_name.removeprefix('bronze_')}"),
                row_count=0, column_count=0, dedup_removed_rows=0, quality_score=0.0,
            )
            self.session.add(silver)
            self.session.commit()
            return silver

        meta_keys = {
            "_bronze_id", "_batch_id", "_source_file_id", "_source_file_name",
            "_source_sheet_name", "_source_row_number", "_raw_record_hash", "_ingested_at",
        }
        data_cols = [k for k in rows[0].keys() if k not in meta_keys]

        # Build typed cleaned columns
        cleaned_by_col: dict[str, list[Any]] = {}
        stats_by_col: dict[str, CleaningStats] = {}
        for col in data_cols:
            cp = next((c for c in profile.columns if c.column_name == col), None)
            if cp is None:
                physical_type, semantic_type = "string", "unknown"
            else:
                physical_type, semantic_type = cp.type_profile.physical_type, cp.type_profile.semantic_type
            raw_values = [r[col] for r in rows]
            cleaned, stats = clean_column(
                col, raw_values, physical_type=physical_type, semantic_type=semantic_type
            )
            cleaned_by_col[col] = cleaned
            stats_by_col[col] = stats

        # Deduplicate on the cleaned values (excluding meta).
        cleaned_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
        seen_hashes: set[str] = set()
        for idx, br in enumerate(rows):
            data_row = {c: cleaned_by_col[c][idx] for c in data_cols}
            row_hash = hash_record(data_row.values())
            if row_hash in seen_hashes:
                continue
            seen_hashes.add(row_hash)
            meta_row = {
                "_bronze_id": br["_bronze_id"],
                "_batch_id": batch_id,
                "_source_file_id": br["_source_file_id"],
                "_source_row_number": br["_source_row_number"],
                "_clean_record_hash": row_hash,
                "_cleaned_at": datetime.utcnow(),
            }
            cleaned_rows.append((meta_row, data_row))

        dedup_removed = len(rows) - len(cleaned_rows)
        table_name = safe_table_name(f"silver_{bronze.table_name.removeprefix('bronze_')}")

        # Create Silver table
        ddl = self._build_create_table(table_name, data_cols, profile)
        with self.silver.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {quote_identifier(table_name)}"))
            conn.execute(text(ddl))

        self._persist_sql(batch_id, f"create_{table_name}.sql", ddl)

        # Insert cleaned rows
        if cleaned_rows:
            all_cols = list(SILVER_META_COLUMNS) + data_cols
            cols_sql = ", ".join(quote_identifier(c) for c in all_cols)
            placeholders = ", ".join([":" + c for c in all_cols])
            stmt = text(
                f"INSERT INTO {quote_identifier(table_name)} ({cols_sql}) "
                f"VALUES ({placeholders})"
            )
            payload = []
            for meta_row, data_row in cleaned_rows:
                payload.append(
                    {
                        "_silver_id": None,
                        "_batch_id": meta_row["_batch_id"],
                        "_bronze_id": meta_row["_bronze_id"],
                        "_source_file_id": meta_row["_source_file_id"],
                        "_source_row_number": meta_row["_source_row_number"],
                        "_clean_record_hash": meta_row["_clean_record_hash"],
                        "_quality_score": _row_quality_score(data_row),
                        "_cleaning_status": "cleaned",
                        "_cleaned_at": meta_row["_cleaned_at"],
                        **{c: _to_db(data_row[c]) for c in data_cols},
                    }
                )
            with self.silver.begin() as conn:
                conn.execute(stmt, payload)

        avg_score = (
            sum(_row_quality_score(d) for _, d in cleaned_rows) / max(1, len(cleaned_rows))
        )
        silver = SilverTable(
            batch_id=batch_id,
            bronze_table_id=bronze.id,
            table_name=table_name,
            row_count=len(cleaned_rows),
            column_count=len(data_cols),
            dedup_removed_rows=dedup_removed,
            quality_score=avg_score,
        )
        self.session.add(silver)
        self.session.commit()
        _log.info(
            "Silver build done batch=%s table=%s rows=%d dedup_removed=%d quality=%.2f",
            batch_id, table_name, len(cleaned_rows), dedup_removed, avg_score,
        )
        return silver

    # ------------------------------------------------------------------
    def list_tables(self, batch_id: str) -> list[SilverTable]:
        return (
            self.session.query(SilverTable)
            .filter(SilverTable.batch_id == batch_id)
            .order_by(SilverTable.created_at)
            .all()
        )

    # ------------------------------------------------------------------
    def _build_create_table(
        self, table_name: str, data_cols: list[str], profile: TableProfileResult
    ) -> str:
        col_profiles = {c.column_name: c for c in profile.columns}
        cols = [
            "  `_silver_id` BIGINT NOT NULL AUTO_INCREMENT",
            "  ,`_batch_id` VARCHAR(64) NOT NULL",
            "  ,`_bronze_id` BIGINT NOT NULL",
            "  ,`_source_file_id` VARCHAR(64) NOT NULL",
            "  ,`_source_row_number` BIGINT NOT NULL",
            "  ,`_clean_record_hash` CHAR(40) NOT NULL",
            "  ,`_quality_score` DOUBLE NULL",
            "  ,`_cleaning_status` VARCHAR(16) NOT NULL",
            "  ,`_cleaned_at` DATETIME NOT NULL",
        ]
        for c in data_cols:
            cp = col_profiles.get(c)
            physical_type = cp.type_profile.physical_type if cp else "string"
            lengths = [len(s) for s in (cp.sample_values if cp else []) if isinstance(s, str)]
            mysql_type = _physical_to_mysql(physical_type, lengths)
            cols.append(f"  ,{quote_identifier(c)} {mysql_type} NULL")
        cols.append("  ,PRIMARY KEY (`_silver_id`)")
        cols.append("  ,KEY `ix_batch` (`_batch_id`)")
        cols.append("  ,KEY `ix_hash` (`_clean_record_hash`)")

        return (
            f"CREATE TABLE {quote_identifier(table_name)} (\n"
            + "\n".join(cols)
            + f"\n) ENGINE=InnoDB {ddl_charset_clause(settings.mysql_charset, settings.mysql_collation)};"
        )

    def _persist_sql(self, batch_id: str, filename: str, sql: str) -> None:
        out = settings.batch_sql_dir(batch_id) / "silver"
        out.mkdir(parents=True, exist_ok=True)
        (out / filename).write_text(sql, encoding="utf-8")


# ---------------------------------------------------------------------------
def _row_quality_score(row: dict[str, Any]) -> float:
    if not row:
        return 0.0
    non_null = sum(1 for v in row.values() if v is not None)
    return non_null / len(row)


def _to_db(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value
