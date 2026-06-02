"""Build the Power BI export package."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models import ApprovedRelationship, ColumnProfile, GoldTable

_log = get_logger(__name__)


class PowerBIExportService:
    """Generates the Power BI directory under ``storage/exports/{batch}/powerbi/``."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    def export(self, batch_id: str) -> Path:
        out = settings.batch_exports_dir(batch_id) / "powerbi"
        out.mkdir(parents=True, exist_ok=True)
        self._write_data_dictionary(batch_id, out)
        self._write_relationships(batch_id, out)
        self._write_dax(batch_id, out)
        self._write_connection_notes(out)
        return out

    # ------------------------------------------------------------------
    def _write_data_dictionary(self, batch_id: str, out: Path) -> None:
        import xlsxwriter  # local import keeps base startup fast

        path = out / "powerbi_data_dictionary.xlsx"
        wb = xlsxwriter.Workbook(str(path))
        try:
            header_fmt = wb.add_format({"bold": True, "bg_color": "#1f3864", "font_color": "white"})

            tables = (
                self.session.query(GoldTable)
                .filter(GoldTable.batch_id == batch_id)
                .all()
            )

            for t in tables:
                sheet_name = t.table_name[:31]
                ws = wb.add_worksheet(sheet_name)
                headers = ["Column", "Original Name", "Physical Type",
                           "Semantic Type", "Null %", "Sample Values"]
                for i, h in enumerate(headers):
                    ws.write(0, i, h, header_fmt)
                cols = (
                    self.session.query(ColumnProfile)
                    .filter(ColumnProfile.batch_id == batch_id,
                            ColumnProfile.table_name == t.table_name)
                    .all()
                )
                for r, c in enumerate(cols, start=1):
                    ws.write(r, 0, c.column_name)
                    ws.write(r, 1, c.original_column_name or "")
                    ws.write(r, 2, c.physical_type)
                    ws.write(r, 3, c.semantic_type)
                    ws.write(r, 4, round(c.null_percentage or 0, 2))
                    ws.write(r, 5, c.sample_values_json or "")
                ws.set_column(0, 5, 28)
        finally:
            wb.close()

    def _write_relationships(self, batch_id: str, out: Path) -> None:
        import xlsxwriter

        path = out / "powerbi_relationships.xlsx"
        wb = xlsxwriter.Workbook(str(path))
        try:
            ws = wb.add_worksheet("Relationships")
            headers = ["From Table", "From Column", "To Table", "To Column",
                       "Cardinality", "Cross-filter Direction"]
            for i, h in enumerate(headers):
                ws.write(0, i, h)
            rels = (
                self.session.query(ApprovedRelationship)
                .filter(ApprovedRelationship.batch_id == batch_id)
                .all()
            )
            for r, rel in enumerate(rels, start=1):
                cardinality = {
                    "one_to_one": "One : One",
                    "one_to_many": "One : Many",
                    "many_to_one": "Many : One",
                    "many_to_many": "Many : Many",
                }.get(rel.relation_type, "Unknown")
                ws.write(r, 0, rel.source_table)
                ws.write(r, 1, rel.source_column)
                ws.write(r, 2, rel.target_table)
                ws.write(r, 3, rel.target_column)
                ws.write(r, 4, cardinality)
                ws.write(r, 5, "Single")
            ws.set_column(0, 5, 24)
        finally:
            wb.close()

    def _write_dax(self, batch_id: str, out: Path) -> None:
        path = out / "suggested_dax_measures.md"
        facts = (
            self.session.query(GoldTable)
            .filter(GoldTable.batch_id == batch_id, GoldTable.role == "fact")
            .all()
        )
        lines = [
            f"# Suggested DAX measures for batch `{batch_id}`",
            f"_Generated at {datetime.utcnow().isoformat()}_\n",
        ]
        if not facts:
            lines.append("> No fact tables detected for this batch.")
        for f in facts:
            measure_cols = [
                c.column_name
                for c in self.session.query(ColumnProfile)
                .filter(ColumnProfile.batch_id == batch_id,
                        ColumnProfile.table_name == f.table_name)
                .all()
                if c.semantic_type in ("amount", "quantity")
            ]
            lines.append(f"## Fact: `{f.table_name}`\n")
            if not measure_cols:
                lines.append("_No numeric measures detected._\n")
                continue
            for col in measure_cols:
                lines.append(f"```dax\nTotal {col} = SUM ( {f.table_name}[{col}] )\n```\n")
                lines.append(
                    f"```dax\nAvg {col} = AVERAGE ( {f.table_name}[{col}] )\n```\n"
                )
        path.write_text("\n".join(lines), encoding="utf-8")

    def _write_connection_notes(self, out: Path) -> None:
        path = out / "mysql_connection_notes.md"
        path.write_text(
            (
                "# Connecting Power BI to the Gold layer\n\n"
                "**Get Data → MySQL database**:\n\n"
                f"- Server: `{settings.mysql_host}:{settings.mysql_port}`\n"
                f"- Database: `{settings.db_gold}`\n"
                "- Authentication: Database (use a read-only MySQL user).\n\n"
                "Use **DirectQuery** for >1M-row facts, **Import** otherwise.\n"
                "Pre-aggregated KPI views (`gold_v_*`) are recommended for\n"
                "dashboard pages with multiple visuals.\n"
            ),
            encoding="utf-8",
        )
