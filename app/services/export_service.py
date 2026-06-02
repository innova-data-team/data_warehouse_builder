"""Aggregate export service.

Combines the SQL generator, Power BI and ZakaaDash packages, the data
quality / relationship reports, and the final cleaned CSV / XLSX files.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import polars as pl
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import gold_engine
from app.core.logging import get_logger
from app.models import ApprovedRelationship, ColumnProfile, GoldTable, QualityIssue
from app.services.powerbi_export_service import PowerBIExportService
from app.services.sql_generator_service import SQLGeneratorService
from app.services.zakaadash_export_service import ZakaaDashExportService

_log = get_logger(__name__)


class ExportService:
    """Orchestrates the per-batch export bundle."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.gold: Engine = gold_engine()
        self.sql_gen = SQLGeneratorService(session)
        self.pbi = PowerBIExportService(session)
        self.zk = ZakaaDashExportService(session)

    # ------------------------------------------------------------------
    def export_all(self, batch_id: str) -> dict[str, str]:
        base = settings.batch_exports_dir(batch_id)
        artifacts: dict[str, str] = {}

        # SQL
        sql_files = self.sql_gen.generate_all(batch_id)
        sql_dir = base / "sql"
        sql_dir.mkdir(parents=True, exist_ok=True)
        for name, path in sql_files.items():
            target = sql_dir / path.name
            target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            artifacts[f"sql:{name}"] = str(target)

        # Power BI / ZakaaDash
        artifacts["powerbi"] = str(self.pbi.export(batch_id))
        artifacts["zakaadash"] = str(self.zk.export(batch_id))

        # Final cleaned files
        artifacts.update(self._export_final_files(batch_id, base / "final_cleaned_files"))

        # Reports
        artifacts.update(self._export_reports(batch_id, base / "reports"))

        return artifacts

    # ------------------------------------------------------------------
    def _export_final_files(self, batch_id: str, out: Path) -> dict[str, str]:
        out.mkdir(parents=True, exist_ok=True)
        result: dict[str, str] = {}
        gold = (
            self.session.query(GoldTable)
            .filter(
                GoldTable.batch_id == batch_id,
                GoldTable.role.in_(("fact", "dim")),
            )
            .all()
        )
        for t in gold:
            try:
                with self.gold.connect() as conn:
                    rows = conn.execute(
                        text(f"SELECT * FROM `{t.table_name}` WHERE `_batch_id` = :bid"),
                        {"bid": batch_id},
                    ).mappings().all()
                df = pl.DataFrame([dict(r) for r in rows]) if rows else pl.DataFrame()
                csv_path = out / f"{t.table_name}.csv"
                df.write_csv(csv_path)
                result[f"final:{t.table_name}"] = str(csv_path)
            except Exception as exc:  # noqa: BLE001
                _log.warning("Could not export %s: %s", t.table_name, exc)
        return result

    def _export_reports(self, batch_id: str, out: Path) -> dict[str, str]:
        out.mkdir(parents=True, exist_ok=True)
        result: dict[str, str] = {}

        # Quality report (JSON + XLSX)
        issues = (
            self.session.query(QualityIssue)
            .filter(QualityIssue.batch_id == batch_id)
            .all()
        )
        qpath_json = out / "data_quality_report.json"
        qpath_json.write_text(
            json.dumps(
                {
                    "batch_id": batch_id,
                    "generated_at": datetime.utcnow().isoformat(),
                    "issues": [
                        {
                            "table_name": i.table_name,
                            "column_name": i.column_name,
                            "issue_type": i.issue_type,
                            "severity": i.severity,
                            "description": i.issue_description,
                            "affected_rows_count": i.affected_rows_count,
                            "auto_fix_available": i.auto_fix_available,
                        }
                        for i in issues
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        result["report:data_quality_json"] = str(qpath_json)

        # Relationships JSON
        rels = (
            self.session.query(ApprovedRelationship)
            .filter(ApprovedRelationship.batch_id == batch_id)
            .all()
        )
        rpath = out / "approved_relationships.json"
        rpath.write_text(
            json.dumps(
                [
                    {
                        "source_table": r.source_table,
                        "source_column": r.source_column,
                        "target_table": r.target_table,
                        "target_column": r.target_column,
                        "relation_type": r.relation_type,
                    }
                    for r in rels
                ],
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
        result["report:relationships_json"] = str(rpath)

        # Data dictionary JSON
        cols = (
            self.session.query(ColumnProfile)
            .filter(ColumnProfile.batch_id == batch_id)
            .all()
        )
        dpath = out / "data_dictionary.json"
        dpath.write_text(
            json.dumps(
                [
                    {
                        "layer": c.layer,
                        "table": c.table_name,
                        "column": c.column_name,
                        "original": c.original_column_name,
                        "physical_type": c.physical_type,
                        "semantic_type": c.semantic_type,
                        "null_percentage": c.null_percentage,
                    }
                    for c in cols
                ],
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
        result["report:data_dictionary_json"] = str(dpath)

        return result
