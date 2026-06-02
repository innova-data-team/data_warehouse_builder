"""Upload endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_metadata_session
from app.schemas.upload_schema import UploadResponse
from app.services.upload_service import UploadService

router = APIRouter(prefix="/upload", tags=["upload"])


@router.post("/files", response_model=UploadResponse)
async def upload_files(
    files: list[UploadFile] = File(...),
    batch_id: str | None = None,
    session: Session = Depends(get_metadata_session),
) -> UploadResponse:
    """Upload one or more files into a new (or existing) batch."""
    service = UploadService(session)
    return await service.upload_batch(files, batch_id=batch_id)
