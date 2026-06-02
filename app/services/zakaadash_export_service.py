"""Build the ZakaaDash export package."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models import ColumnProfile, GoldTable

_log = get_logger(__name__)


class ZakaaDashExportService:
    """Generates the ZakaaDash directory under ``storage/exports/{batch}/zakaadash/``."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    def export(self, batch_id: str) -> Path:
        out = settings.batch_exports_dir(batch_id) / "zakaadash"
        out.mkdir(parents=True, exist_ok=True)
        self._write_views_sql(batch_id, out)
        self._write_dashboard_objectives(batch_id, out)
        self._write_chart_recommendations(batch_id, out)
        self._write_bilingual_dictionary(batch_id, out)
        return out

    # ------------------------------------------------------------------
    def _write_views_sql(self, batch_id: str, out: Path) -> None:
        path = out / "zakaadash_views.sql"
        views = (
            self.session.query(GoldTable)
            .filter(
                GoldTable.batch_id == batch_id,
                GoldTable.role.in_(("view", "kpi_view")),
            )
            .all()
        )
        if not views:
            path.write_text("-- no Gold views available for this batch\n", encoding="utf-8")
            return
        lines = [f"-- ZakaaDash-ready views for batch {batch_id}", ""]
        for v in views:
            lines.append(
                f"-- {v.role}: {v.table_name} (sources: {v.source_silver_tables})"
            )
            lines.append(
                f"-- SELECT * FROM {settings.db_gold}.`{v.table_name}` LIMIT 100;"
            )
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")

    def _write_dashboard_objectives(self, batch_id: str, out: Path) -> None:
        path = out / "dashboard_objectives.json"
        facts = (
            self.session.query(GoldTable)
            .filter(GoldTable.batch_id == batch_id, GoldTable.role == "fact")
            .all()
        )
        objectives = [
            {
                "objective_id": f"obj_{i + 1}",
                "fact_table": f.table_name,
                "title_en": f"Analyze {f.table_name.removeprefix('gold_fact_')}",
                "title_ar": f"تحليل بيانات {f.table_name.removeprefix('gold_fact_')}",
                "kpis": [],
                "filters": [],
            }
            for i, f in enumerate(facts)
        ]
        path.write_text(
            json.dumps({"batch_id": batch_id, "objectives": objectives},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_chart_recommendations(self, batch_id: str, out: Path) -> None:
        path = out / "chart_recommendations.json"
        recs = []
        facts = (
            self.session.query(GoldTable)
            .filter(GoldTable.batch_id == batch_id, GoldTable.role == "fact")
            .all()
        )
        for f in facts:
            measures = [
                c.column_name
                for c in self.session.query(ColumnProfile)
                .filter(ColumnProfile.batch_id == batch_id,
                        ColumnProfile.table_name == f.table_name)
                .all()
                if c.semantic_type in ("amount", "quantity")
            ]
            dims = [
                c.column_name
                for c in self.session.query(ColumnProfile)
                .filter(ColumnProfile.batch_id == batch_id,
                        ColumnProfile.table_name == f.table_name)
                .all()
                if c.semantic_type in ("category", "status", "code", "name")
            ]
            for m in measures:
                recs.append(
                    {
                        "chart_id": f"{f.table_name}__total_{m}",
                        "chart_title_en": f"Total {m}",
                        "chart_title_ar": f"إجمالي {m}",
                        "chart_type": "kpi_card",
                        "view": f.table_name,
                        "dimension_columns": [],
                        "measure_columns": [m],
                        "aggregation": "sum",
                        "filter_columns": dims[:3],
                        "drilldown_columns": dims[:2],
                        "business_question_en": f"What is the total {m}?",
                        "business_question_ar": f"ما هو إجمالي {m}؟",
                    }
                )
        path.write_text(
            json.dumps({"batch_id": batch_id, "charts": recs}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_bilingual_dictionary(self, batch_id: str, out: Path) -> None:
        import xlsxwriter

        path = out / "arabic_english_data_dictionary.xlsx"
        wb = xlsxwriter.Workbook(str(path))
        try:
            ws = wb.add_worksheet("Dictionary")
            headers = ["Table", "Column (EN)", "Column (AR / Original)",
                       "Physical Type", "Semantic Type"]
            for i, h in enumerate(headers):
                ws.write(0, i, h)
            cols = (
                self.session.query(ColumnProfile)
                .filter(ColumnProfile.batch_id == batch_id)
                .all()
            )
            for r, c in enumerate(cols, start=1):
                ws.write(r, 0, c.table_name)
                ws.write(r, 1, c.column_name)
                ws.write(r, 2, c.original_column_name or "")
                ws.write(r, 3, c.physical_type)
                ws.write(r, 4, c.semantic_type)
            ws.set_column(0, 4, 28)
        finally:
            wb.close()
