"""Pipeline orchestration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_metadata_session
from app.schemas.pipeline_schema import BronzeTableInfo, PipelineStatus, SilverTableInfo
from app.services.pipeline_service import PipelineService, require_batch

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.post("/{batch_id}/run", response_model=PipelineStatus)
def run_full_pipeline(
    batch_id: str,
    session: Session = Depends(get_metadata_session),
) -> PipelineStatus:
    """Run Bronze → Silver → DQ → Relationship detection (stops before Gold)."""
    return PipelineService(session).run_until_approval(batch_id)


@router.get("/{batch_id}/status", response_model=PipelineStatus)
def get_status(
    batch_id: str,
    session: Session = Depends(get_metadata_session),
) -> PipelineStatus:
    return PipelineService(session).status(batch_id)


@router.post("/{batch_id}/bronze/run", response_model=list[BronzeTableInfo])
def run_bronze(
    batch_id: str,
    session: Session = Depends(get_metadata_session),
) -> list[BronzeTableInfo]:
    tables = PipelineService(session).run_bronze(batch_id)
    return [
        BronzeTableInfo(
            table_name=t.table_name,
            source_file=t.source_file_name,
            source_sheet=t.source_sheet_name,
            row_count=t.row_count,
            column_count=t.column_count,
        )
        for t in tables
    ]


@router.get("/{batch_id}/bronze/tables", response_model=list[BronzeTableInfo])
def list_bronze(
    batch_id: str,
    session: Session = Depends(get_metadata_session),
) -> list[BronzeTableInfo]:
    require_batch(session, batch_id)
    from app.services.bronze_service import BronzeService

    return [
        BronzeTableInfo(
            table_name=t.table_name,
            source_file=t.source_file_name,
            source_sheet=t.source_sheet_name,
            row_count=t.row_count,
            column_count=t.column_count,
        )
        for t in BronzeService(session).list_tables(batch_id)
    ]


@router.post("/{batch_id}/silver/run", response_model=list[SilverTableInfo])
def run_silver(
    batch_id: str,
    session: Session = Depends(get_metadata_session),
) -> list[SilverTableInfo]:
    tables = PipelineService(session).run_silver(batch_id)
    return [
        SilverTableInfo(
            table_name=t.table_name,
            source_bronze_table="(see metadata)",
            row_count=t.row_count,
            column_count=t.column_count,
            quality_score=t.quality_score,
        )
        for t in tables
    ]


@router.get("/{batch_id}/silver/tables", response_model=list[SilverTableInfo])
def list_silver(
    batch_id: str,
    session: Session = Depends(get_metadata_session),
) -> list[SilverTableInfo]:
    require_batch(session, batch_id)
    from app.services.silver_service import SilverService

    return [
        SilverTableInfo(
            table_name=t.table_name,
            source_bronze_table="(see metadata)",
            row_count=t.row_count,
            column_count=t.column_count,
            quality_score=t.quality_score,
        )
        for t in SilverService(session).list_tables(batch_id)
    ]


@router.post("/{batch_id}/gold/run")
def run_gold(
    batch_id: str,
    session: Session = Depends(get_metadata_session),
) -> dict[str, object]:
    outputs = PipelineService(session).run_gold(batch_id)
    return {
        "batch_id": batch_id,
        "created": len(outputs),
        "tables": [{"name": o.table_name, "role": o.role} for o in outputs],
    }


@router.get("/{batch_id}/gold/tables")
def list_gold_tables(
    batch_id: str,
    session: Session = Depends(get_metadata_session),
) -> list[dict[str, object]]:
    require_batch(session, batch_id)
    from app.services.gold_service import GoldBuilder

    return [
        {"name": t.table_name, "role": t.role, "sources": t.source_silver_tables}
        for t in GoldBuilder(session).list_tables(batch_id)
        if t.role in ("fact", "dim")
    ]


@router.get("/{batch_id}/gold/views")
def list_gold_views(
    batch_id: str,
    session: Session = Depends(get_metadata_session),
) -> list[dict[str, object]]:
    require_batch(session, batch_id)
    from app.services.gold_service import GoldBuilder

    return [
        {"name": t.table_name, "role": t.role, "sources": t.source_silver_tables}
        for t in GoldBuilder(session).list_tables(batch_id)
        if t.role in ("view", "kpi_view")
    ]
