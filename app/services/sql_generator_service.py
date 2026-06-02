"""Top-level SQL generator.

The individual services (Bronze, Silver, Gold) already persist their own
``.sql`` files into ``sql/generated/{batch_id}/<layer>/``. This service
provides the **batch-level umbrella scripts** so a DBA can replay an
entire batch from a single ``mysql -e "source ..."`` invocation, plus
the static cross-batch scripts (``create_databases.sql``,
``create_metadata_tables.sql``).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models import BronzeTable, GoldTable, SilverTable
from app.utils.sql_utils import ddl_charset_clause, quote_identifier

_log = get_logger(__name__)


class SQLGeneratorService:
    """Assemble batch-level umbrella SQL scripts."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    def generate_all(self, batch_id: str) -> dict[str, Path]:
        out_dir = settings.batch_sql_dir(batch_id)
        files: dict[str, Path] = {
            "create_databases":     self._write_create_databases(out_dir),
            "create_bronze_tables": self._write_layer_umbrella(batch_id, "bronze", out_dir),
            "create_silver_tables": self._write_layer_umbrella(batch_id, "silver", out_dir),
            "create_gold_tables":   self._write_layer_umbrella(batch_id, "gold",   out_dir),
            "create_gold_views":    self._write_layer_umbrella(batch_id, "views",  out_dir),
            "create_indexes":       self._write_indexes(batch_id, out_dir),
        }
        return files

    # ------------------------------------------------------------------
    def _write_create_databases(self, out_dir: Path) -> Path:
        sql = (
            f"-- generated at {datetime.utcnow().isoformat()}\n"
            f"CREATE DATABASE IF NOT EXISTS {quote_identifier(settings.db_metadata)} {ddl_charset_clause()};\n"
            f"CREATE DATABASE IF NOT EXISTS {quote_identifier(settings.db_bronze)}   {ddl_charset_clause()};\n"
            f"CREATE DATABASE IF NOT EXISTS {quote_identifier(settings.db_silver)}   {ddl_charset_clause()};\n"
            f"CREATE DATABASE IF NOT EXISTS {quote_identifier(settings.db_gold)}     {ddl_charset_clause()};\n"
        )
        path = out_dir / "create_databases.sql"
        path.write_text(sql, encoding="utf-8")
        return path

    def _write_layer_umbrella(self, batch_id: str, layer: str, out_dir: Path) -> Path:
        layer_dir = out_dir / layer
        layer_dir.mkdir(parents=True, exist_ok=True)
        parts = sorted(layer_dir.glob("*.sql"))
        body_lines = [f"-- {layer.upper()} layer for batch {batch_id}",
                      f"-- generated at {datetime.utcnow().isoformat()}",
                      ""]
        for p in parts:
            body_lines.append(f"-- ===== {p.name} =====")
            body_lines.append(p.read_text(encoding="utf-8"))
            body_lines.append("")
        path = out_dir / f"create_{layer}_tables.sql" if layer != "views" else out_dir / "create_gold_views.sql"
        path.write_text("\n".join(body_lines), encoding="utf-8")
        return path

    def _write_indexes(self, batch_id: str, out_dir: Path) -> Path:
        # Suggest indexes for every FK and every column with semantic_type='id'.
        # Real generation happens here; we keep it simple at scaffold level.
        bronze = self.session.query(BronzeTable).filter(BronzeTable.batch_id == batch_id).all()
        silver = self.session.query(SilverTable).filter(SilverTable.batch_id == batch_id).all()
        gold = self.session.query(GoldTable).filter(GoldTable.batch_id == batch_id).all()

        lines = [f"-- Index suggestions for batch {batch_id}",
                 f"-- generated at {datetime.utcnow().isoformat()}",
                 ""]
        for t in bronze:
            lines.append(
                f"-- CREATE INDEX `ix_{t.table_name}_file` "
                f"ON {settings.db_bronze}.{quote_identifier(t.table_name)} (`_source_file_id`);"
            )
        for t in silver:
            lines.append(
                f"-- CREATE INDEX `ix_{t.table_name}_batch` "
                f"ON {settings.db_silver}.{quote_identifier(t.table_name)} (`_batch_id`);"
            )
        for t in gold:
            lines.append(
                f"-- CREATE INDEX `ix_{t.table_name}_batch` "
                f"ON {settings.db_gold}.{quote_identifier(t.table_name)} (`_batch_id`);"
            )

        path = out_dir / "create_indexes.sql"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path
