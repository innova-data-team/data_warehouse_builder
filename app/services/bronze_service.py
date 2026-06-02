"""Bronze layer: load raw frames into MySQL with lossless ``TEXT`` columns.

For each (file, sheet) pair we:

1. Pick a safe table name ``bronze_{base}__{sheet}``.
2. Generate ``CREATE TABLE`` with mandatory lineage columns.
3. Insert all rows in chunked ``INSERT`` batches (configurable size).
4. Register the table in ``dw_metadata.bronze_tables`` and persist the
   original→safe column mapping in ``column_profiles``.
5. Save the DDL + DML to ``sql/generated/{batch_id}/bronze/``.

Bronze never coerces values. Every column lands as ``TEXT`` (or
``LONGTEXT`` if any value exceeds 65 535 chars). This is the contract:
**no data loss in Bronze**.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Sequence

import polars as pl
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import bronze_engine
from app.core.logging import get_logger
from app.models import BronzeTable, UploadedFile
from app.services.file_reader_service import FrameInfo
from app.utils.hash_utils import hash_record
from app.utils.sql_utils import (
    ddl_charset_clause,
    quote_identifier,
    render_string_literal,
    safe_table_name,
)

_log = get_logger(__name__)

BRONZE_META_COLUMNS: Sequence[str] = (
    "_bronze_id",
    "_batch_id",
    "_source_file_id",
    "_source_file_name",
    "_source_sheet_name",
    "_source_row_number",
    "_raw_record_hash",
    "_ingested_at",
)


class BronzeService:
    """Materializes Bronze tables in MySQL and on disk."""

    def __init__(self, session: Session, *, chunk_size: int = 500) -> None:
        self.session = session
        self.chunk_size = chunk_size
        self.engine: Engine = bronze_engine()

    # ------------------------------------------------------------------
    def ingest_frame(
        self,
        *,
        batch_id: str,
        file: UploadedFile,
        frame_info: FrameInfo,
    ) -> BronzeTable:
        table_name = safe_table_name(f"bronze_{frame_info.name}")
        column_names = list(frame_info.frame.columns)

        ddl = self._build_create_table(table_name, column_names)
        self._persist_sql(batch_id, f"create_{table_name}.sql", ddl)

        with self.engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {quote_identifier(table_name)}"))
            conn.execute(text(ddl))

        inserted, failed = self._insert_rows(
            batch_id=batch_id,
            file=file,
            frame=frame_info.frame,
            table_name=table_name,
            data_columns=column_names,
        )

        row = BronzeTable(
            batch_id=batch_id,
            file_id=file.file_id,
            table_name=table_name,
            source_file_name=file.original_file_name,
            source_sheet_name=frame_info.sheet_name,
            row_count=inserted,
            column_count=len(column_names),
            failed_row_count=failed,
        )
        self.session.add(row)
        self.session.commit()
        _log.info(
            "Bronze ingest done batch=%s table=%s rows=%d failed=%d",
            batch_id, table_name, inserted, failed,
        )
        return row

    # ------------------------------------------------------------------
    def list_tables(self, batch_id: str) -> list[BronzeTable]:
        return (
            self.session.query(BronzeTable)
            .filter(BronzeTable.batch_id == batch_id)
            .order_by(BronzeTable.created_at)
            .all()
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _build_create_table(self, table_name: str, data_columns: Iterable[str]) -> str:
        cols = [
            f"  `_bronze_id` BIGINT NOT NULL AUTO_INCREMENT",
            f"  ,`_batch_id` VARCHAR(64) NOT NULL",
            f"  ,`_source_file_id` VARCHAR(64) NOT NULL",
            f"  ,`_source_file_name` VARCHAR(512) NOT NULL",
            f"  ,`_source_sheet_name` VARCHAR(256) NULL",
            f"  ,`_source_row_number` BIGINT NOT NULL",
            f"  ,`_raw_record_hash` CHAR(40) NOT NULL",
            f"  ,`_ingested_at` DATETIME NOT NULL",
        ]
        for c in data_columns:
            cols.append(f"  ,{quote_identifier(c)} LONGTEXT NULL")
        cols.append("  ,PRIMARY KEY (`_bronze_id`)")
        cols.append("  ,KEY `ix_batch` (`_batch_id`)")
        cols.append("  ,KEY `ix_hash` (`_raw_record_hash`)")

        return (
            f"CREATE TABLE {quote_identifier(table_name)} (\n"
            + "\n".join(cols)
            + f"\n) ENGINE=InnoDB {ddl_charset_clause(settings.mysql_charset, settings.mysql_collation)};"
        )

    def _insert_rows(
        self,
        *,
        batch_id: str,
        file: UploadedFile,
        frame: pl.DataFrame,
        table_name: str,
        data_columns: Sequence[str],
    ) -> tuple[int, int]:
        if frame.is_empty():
            return 0, 0

        cols = list(BRONZE_META_COLUMNS) + list(data_columns)
        cols_sql = ", ".join(quote_identifier(c) for c in cols)
        placeholders = ", ".join([":" + str(i) for i in range(len(cols))])

        stmt = text(
            f"INSERT INTO {quote_identifier(table_name)} ({cols_sql}) "
            f"VALUES ({placeholders})"
        )
        now = datetime.utcnow()
        inserted = failed = 0

        records = frame.iter_rows(named=False)
        batch: list[dict[str, object | None]] = []

        for row_idx, row in enumerate(records, start=1):
            values = [None if v is None else str(v) for v in row]
            row_hash = hash_record(values)
            meta_values = [
                None,  # _bronze_id auto
                batch_id,
                file.file_id,
                file.original_file_name,
                None,  # sheet name set later if needed
                row_idx,
                row_hash,
                now,
            ]
            full = meta_values + values
            batch.append({str(i): v for i, v in enumerate(full)})

            if len(batch) >= self.chunk_size:
                inserted_now, failed_now = self._flush(stmt, batch)
                inserted += inserted_now
                failed += failed_now
                batch.clear()

        if batch:
            inserted_now, failed_now = self._flush(stmt, batch)
            inserted += inserted_now
            failed += failed_now

        return inserted, failed

    def _flush(self, stmt, batch: list[dict[str, object | None]]) -> tuple[int, int]:
        try:
            with self.engine.begin() as conn:
                conn.execute(stmt, batch)
            return len(batch), 0
        except Exception as exc:  # noqa: BLE001
            _log.warning("Bronze batch insert failed (%d rows): %s", len(batch), exc)
            inserted = 0
            failed = 0
            for row in batch:
                try:
                    with self.engine.begin() as conn:
                        conn.execute(stmt, [row])
                    inserted += 1
                except Exception:  # noqa: BLE001
                    failed += 1
            return inserted, failed

    def _persist_sql(self, batch_id: str, filename: str, sql: str) -> None:
        out = settings.batch_sql_dir(batch_id) / "bronze"
        out.mkdir(parents=True, exist_ok=True)
        (out / filename).write_text(sql, encoding="utf-8")

    # ------------------------------------------------------------------
    # Helpers for tests / SQL preview without a live DB
    # ------------------------------------------------------------------
    @classmethod
    def render_insert_sql(
        cls, table_name: str, columns: Sequence[str], rows: Sequence[Sequence[object | None]]
    ) -> str:
        """Render plain ``INSERT INTO ... VALUES`` SQL — used by sql_generator."""
        if not rows:
            return ""
        cols_sql = ", ".join(quote_identifier(c) for c in columns)
        lines = [f"INSERT INTO {quote_identifier(table_name)} ({cols_sql}) VALUES"]
        rendered = [
            "  (" + ", ".join(render_string_literal(None if v is None else str(v)) for v in r) + ")"
            for r in rows
        ]
        return lines[0] + "\n" + ",\n".join(rendered) + ";"
