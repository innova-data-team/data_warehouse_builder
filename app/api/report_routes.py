"""Quality / data-dictionary / lineage report endpoints."""

from __future__ import annotations

import json
from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_metadata_session
from app.models import (
    BronzeTable,
    ColumnProfile,
    GoldTable,
    QualityIssue,
    SilverTable,
)
from app.schemas.relationship_schema import RelationshipSuggestionList
from app.schemas.report_schema import (
    ColumnDictionaryEntry,
    DataDictionary,
    LineageEdge,
    LineageReport,
    QualityIssueOut,
    QualityReport,
    Severity,
)
from app.services.relationship_approval_service import RelationshipApprovalService

router = APIRouter(prefix="/reports", tags=["reports"])


# ---------------------------------------------------------------------------
@router.get("/{batch_id}/quality", response_model=QualityReport)
def quality_report(
    batch_id: str,
    session: Session = Depends(get_metadata_session),
) -> QualityReport:
    issues = (
        session.query(QualityIssue)
        .filter(QualityIssue.batch_id == batch_id)
        .order_by(QualityIssue.severity, QualityIssue.table_name)
        .all()
    )
    by_sev = Counter(i.severity for i in issues)

    out: list[QualityIssueOut] = []
    for i in issues:
        try:
            samples = json.loads(i.sample_values_json or "[]")
        except json.JSONDecodeError:
            samples = []
        out.append(
            QualityIssueOut(
                issue_id=i.id,
                batch_id=i.batch_id,
                layer=i.layer,  # type: ignore[arg-type]
                table_name=i.table_name,
                column_name=i.column_name,
                issue_type=i.issue_type,
                severity=i.severity,  # type: ignore[arg-type]
                issue_description=i.issue_description,
                affected_rows_count=i.affected_rows_count or 0,
                affected_rows_percentage=i.affected_rows_percentage or 0.0,
                sample_values=[str(s) for s in samples],
                suggested_fix=i.suggested_fix,
                auto_fix_available=i.auto_fix_available,
                auto_fix_applied=i.auto_fix_applied,
            )
        )
    return QualityReport(
        batch_id=batch_id,
        total_issues=len(issues),
        by_severity={k: v for k, v in by_sev.items()},  # type: ignore[arg-type]
        issues=out,
    )


# ---------------------------------------------------------------------------
@router.get("/{batch_id}/relationships", response_model=RelationshipSuggestionList)
def relationship_report(
    batch_id: str,
    session: Session = Depends(get_metadata_session),
) -> RelationshipSuggestionList:
    # Reuse the relationship_routes mapper to avoid duplication
    from app.api.relationship_routes import _to_schema  # local import

    suggestions = RelationshipApprovalService(session).list_suggestions(batch_id)
    return RelationshipSuggestionList(
        batch_id=batch_id,
        total=len(suggestions),
        suggestions=[_to_schema(s) for s in suggestions],
    )


# ---------------------------------------------------------------------------
@router.get("/{batch_id}/data-dictionary", response_model=DataDictionary)
def data_dictionary(
    batch_id: str,
    session: Session = Depends(get_metadata_session),
) -> DataDictionary:
    cols = (
        session.query(ColumnProfile)
        .filter(ColumnProfile.batch_id == batch_id)
        .all()
    )
    entries = [
        ColumnDictionaryEntry(
            table_name=c.table_name,
            column_name=c.column_name,
            original_name=c.original_column_name,
            physical_type=c.physical_type,
            semantic_type=c.semantic_type,
            null_percentage=c.null_percentage or 0.0,
            sample_values=json.loads(c.sample_values_json or "[]"),
            is_arabic=(c.arabic_text_percentage or 0) > 30,
        )
        for c in cols
    ]
    return DataDictionary(batch_id=batch_id, total_columns=len(entries), columns=entries)


# ---------------------------------------------------------------------------
@router.get("/{batch_id}/lineage", response_model=LineageReport)
def lineage(
    batch_id: str,
    session: Session = Depends(get_metadata_session),
) -> LineageReport:
    edges: list[LineageEdge] = []

    for b in session.query(BronzeTable).filter(BronzeTable.batch_id == batch_id).all():
        edges.append(
            LineageEdge(
                from_layer="raw", from_object=b.source_file_name,
                to_layer="bronze", to_object=b.table_name,
            )
        )
    for s in session.query(SilverTable).filter(SilverTable.batch_id == batch_id).all():
        edges.append(
            LineageEdge(
                from_layer="bronze",
                from_object=f"(bronze_table_id={s.bronze_table_id})",
                to_layer="silver", to_object=s.table_name,
            )
        )
    for g in session.query(GoldTable).filter(GoldTable.batch_id == batch_id).all():
        for src in (g.source_silver_tables or "").split(","):
            src = src.strip()
            if not src:
                continue
            edges.append(
                LineageEdge(
                    from_layer="silver", from_object=src,
                    to_layer="gold", to_object=g.table_name,
                )
            )
    return LineageReport(batch_id=batch_id, edges=edges)
