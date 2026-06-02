"""Unified backend — file storage or MySQL based on ``STORAGE_BACKEND``."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import session_scope
from app.services.file_pipeline_service import FilePipelineService
from app.services.pipeline_service import PipelineService
from app.services.upload_service import UploadService


def use_file_storage() -> bool:
    return settings.use_file_storage


def list_batches() -> list[str]:
    if use_file_storage():
        return FilePipelineService.list_batches()
    try:
        from sqlalchemy import text
        from app.core.database import metadata_engine
        from app.models import Batch

        with metadata_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        with session_scope() as session:
            rows = (
                session.query(Batch.batch_id)
                .order_by(Batch.created_at.desc())
                .limit(50)
                .all()
            )
            return [r[0] for r in rows]
    except Exception:
        return FilePipelineService.list_batches()


def get_file_pipeline() -> FilePipelineService:
    return FilePipelineService()


@contextmanager
def pipeline_context() -> Iterator[PipelineService | FilePipelineService]:
    if use_file_storage():
        yield FilePipelineService()
    else:
        with session_scope() as session:
            yield PipelineService(session)


@contextmanager
def upload_context() -> Iterator[UploadService | FilePipelineService]:
    if use_file_storage():
        yield FilePipelineService()
    else:
        with session_scope() as session:
            yield UploadService(session)
