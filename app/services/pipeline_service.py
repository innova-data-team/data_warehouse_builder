"""Pipeline orchestration — shared by the FastAPI routes and Streamlit UI."""

from __future__ import annotations

from datetime import datetime

import polars as pl
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import bronze_engine
from app.core.exceptions import NotFoundError
from app.models import (
    ApprovedRelationship,
    BronzeTable,
    GoldTable,
    QualityIssue,
    RelationshipSuggestion,
    SilverTable,
    UploadedFile,
)
from app.schemas.pipeline_schema import PipelineStageResult, PipelineStatus
from app.services.bronze_service import BronzeService
from app.services.data_quality_service import DataQualityService
from app.services.file_reader_service import read_file
from app.services.gold_service import GoldBuilder
from app.services.profiler_service import ProfilerService
from app.services.relationship_detector_service import RelationshipDetectorService
from app.services.silver_service import SilverService
from app.services.upload_service import UploadService


def require_batch(session: Session, batch_id: str) -> None:
    if not session.query(UploadedFile).filter(UploadedFile.batch_id == batch_id).first():
        raise NotFoundError(f"Unknown batch_id '{batch_id}'.")


def load_bronze_frame(batch_id: str, bronze_table: str) -> pl.DataFrame:
    """Load a Bronze table (data columns only) as a Polars frame."""
    with bronze_engine().connect() as conn:
        rows = conn.execute(
            text(f"SELECT * FROM `{bronze_table}` WHERE `_batch_id` = :bid"),
            {"bid": batch_id},
        ).mappings().all()
    if not rows:
        return pl.DataFrame()
    data: dict[str, list] = {k: [] for k in rows[0].keys() if not k.startswith("_")}
    for r in rows:
        for k in data:
            data[k].append(r[k])
    return pl.DataFrame(data)


def build_status(
    session: Session, batch_id: str, stages: list[PipelineStageResult] | None = None
) -> PipelineStatus:
    bronze_tables = [
        t.table_name
        for t in session.query(BronzeTable).filter(BronzeTable.batch_id == batch_id)
    ]
    silver_tables = [
        t.table_name
        for t in session.query(SilverTable).filter(SilverTable.batch_id == batch_id)
    ]
    gold = session.query(GoldTable).filter(GoldTable.batch_id == batch_id).all()
    gold_tables = [t.table_name for t in gold if t.role in ("fact", "dim")]
    gold_views = [t.table_name for t in gold if t.role in ("view", "kpi_view")]
    suggestion_count = session.query(RelationshipSuggestion).filter(
        RelationshipSuggestion.batch_id == batch_id
    ).count()
    approved_count = session.query(ApprovedRelationship).filter(
        ApprovedRelationship.batch_id == batch_id
    ).count()
    issue_count = session.query(QualityIssue).filter(
        QualityIssue.batch_id == batch_id
    ).count()

    if gold_tables:
        current = "gold_done"
    elif suggestion_count > 0:
        current = "awaiting_approval"
    elif silver_tables:
        current = "silver_done"
    elif bronze_tables:
        current = "bronze_done"
    else:
        current = "uploaded"

    return PipelineStatus(
        batch_id=batch_id,
        current_stage=current,  # type: ignore[arg-type]
        stages=stages or [],
        bronze_tables=bronze_tables,
        silver_tables=silver_tables,
        gold_tables=gold_tables,
        gold_views=gold_views,
        suggestion_count=suggestion_count,
        approved_count=approved_count,
        quality_issue_count=issue_count,
    )


class PipelineService:
    """Run pipeline stages for a batch."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def run_until_approval(self, batch_id: str) -> PipelineStatus:
        """Bronze → Silver → DQ → relationship detection (stops before Gold)."""
        require_batch(self.session, batch_id)
        upload_service = UploadService(self.session)
        bronze = BronzeService(self.session)
        profiler = ProfilerService(self.session)
        dq = DataQualityService(self.session)
        silver = SilverService(self.session)
        detector = RelationshipDetectorService(self.session)
        stages: list[PipelineStageResult] = []

        started = datetime.utcnow()
        for f in upload_service.list_files(batch_id):
            read = read_file(f.stored_file_path)
            for frame_info in read.frames:
                br = bronze.ingest_frame(batch_id=batch_id, file=f, frame_info=frame_info)
                tp = profiler.profile_table(
                    batch_id=batch_id,
                    layer="bronze",
                    table_name=br.table_name,
                    frame=frame_info.frame,
                    original_column_names=frame_info.original_columns,
                )
                dq.run(batch_id=batch_id, table_profile=tp, frame=frame_info.frame)
        stages.append(
            PipelineStageResult(
                stage="bronze_done", started_at=started, finished_at=datetime.utcnow()
            )
        )

        started = datetime.utcnow()
        for b in bronze.list_tables(batch_id):
            frame = load_bronze_frame(batch_id, b.table_name)
            tp = profiler.profile_table(
                batch_id=batch_id,
                layer="silver",
                table_name=b.table_name,
                frame=frame,
            )
            silver.build_from_bronze(batch_id=batch_id, bronze=b, profile=tp)
        stages.append(
            PipelineStageResult(
                stage="silver_done", started_at=started, finished_at=datetime.utcnow()
            )
        )

        started = datetime.utcnow()
        suggestions = detector.detect(batch_id)
        stages.append(
            PipelineStageResult(
                stage="relationships_detected",
                started_at=started,
                finished_at=datetime.utcnow(),
                message=f"{len(suggestions)} suggestion(s); awaiting approval.",
            )
        )
        return build_status(self.session, batch_id, stages)

    def run_bronze(self, batch_id: str) -> list[BronzeTable]:
        require_batch(self.session, batch_id)
        bronze = BronzeService(self.session)
        profiler = ProfilerService(self.session)
        dq = DataQualityService(self.session)
        for f in UploadService(self.session).list_files(batch_id):
            read = read_file(f.stored_file_path)
            for frame_info in read.frames:
                br = bronze.ingest_frame(batch_id=batch_id, file=f, frame_info=frame_info)
                tp = profiler.profile_table(
                    batch_id=batch_id,
                    layer="bronze",
                    table_name=br.table_name,
                    frame=frame_info.frame,
                    original_column_names=frame_info.original_columns,
                )
                dq.run(batch_id=batch_id, table_profile=tp, frame=frame_info.frame)
        return bronze.list_tables(batch_id)

    def run_silver(self, batch_id: str) -> list[SilverTable]:
        require_batch(self.session, batch_id)
        bronze = BronzeService(self.session)
        profiler = ProfilerService(self.session)
        silver = SilverService(self.session)
        for b in bronze.list_tables(batch_id):
            frame = load_bronze_frame(batch_id, b.table_name)
            tp = profiler.profile_table(
                batch_id=batch_id, layer="silver", table_name=b.table_name, frame=frame
            )
            silver.build_from_bronze(batch_id=batch_id, bronze=b, profile=tp)
        return silver.list_tables(batch_id)

    def run_relationships(self, batch_id: str) -> list[RelationshipSuggestion]:
        require_batch(self.session, batch_id)
        return RelationshipDetectorService(self.session).detect(batch_id)

    def run_gold(self, batch_id: str) -> list[GoldTable]:
        require_batch(self.session, batch_id)
        return GoldBuilder(self.session).build(batch_id)

    def status(self, batch_id: str) -> PipelineStatus:
        require_batch(self.session, batch_id)
        return build_status(self.session, batch_id)
