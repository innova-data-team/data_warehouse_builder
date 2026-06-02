"""Handles incoming file uploads: validates, stores, registers metadata."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import FileFormatError, ValidationError
from app.core.logging import get_logger
from app.models import Batch, UploadedFile
from app.schemas.upload_schema import UploadedFileInfo, UploadResponse
from app.utils.file_utils import (
    detect_file_format,
    new_batch_id,
    new_file_id,
    safe_filename,
)
from app.utils.hash_utils import hash_file_sha256

_log = get_logger(__name__)


class UploadService:
    """Persist uploaded files to ``storage/raw/{batch_id}/`` and register them."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    def upload_batch_sync(
        self,
        files: Iterable[tuple[str, bytes]],
        *,
        batch_id: str | None = None,
        created_by: str | None = None,
    ) -> UploadResponse:
        """Synchronous upload for CLI / Streamlit (filename + raw bytes pairs)."""
        batch_id = batch_id or new_batch_id()
        batch_dir = settings.batch_raw_dir(batch_id)

        if self.session.get(Batch, batch_id) is None:
            self.session.add(
                Batch(
                    batch_id=batch_id,
                    status="uploaded",
                    current_stage="uploaded",
                    created_by=created_by,
                )
            )
            self.session.flush()

        infos: list[UploadedFileInfo] = []
        total_bytes = 0
        max_bytes = settings.max_upload_mb * 1024 * 1024

        for filename, content in files:
            if not filename:
                raise ValidationError("Upload missing filename.")
            file_type = detect_file_format(filename)
            if file_type == "unknown":
                raise FileFormatError(
                    f"Unsupported file type for '{filename}'."
                )
            if len(content) > max_bytes:
                raise ValidationError(
                    f"File '{filename}' exceeds MAX_UPLOAD_MB="
                    f"{settings.max_upload_mb}MB."
                )

            safe_name = safe_filename(filename)
            file_id = new_file_id()
            stored_path = batch_dir / f"{file_id}__{safe_name}"
            stored_path.write_bytes(content)
            total_bytes += len(content)

            file_hash = hash_file_sha256(stored_path)
            self.session.add(
                UploadedFile(
                    file_id=file_id,
                    batch_id=batch_id,
                    original_file_name=filename,
                    stored_file_path=str(stored_path),
                    file_type=file_type,
                    file_size=len(content),
                    file_hash=file_hash,
                    upload_time=datetime.utcnow(),
                    status="uploaded",
                )
            )
            infos.append(
                UploadedFileInfo(
                    file_id=file_id,
                    original_file_name=filename,
                    stored_file_path=str(stored_path),
                    file_type=file_type,
                    file_size=len(content),
                    file_hash=file_hash,
                )
            )
            _log.info(
                "Stored upload batch=%s file=%s bytes=%d type=%s",
                batch_id, filename, len(content), file_type,
            )

        self.session.commit()
        return UploadResponse(
            batch_id=batch_id,
            files=infos,
            total_files=len(infos),
            total_bytes=total_bytes,
        )

    # ------------------------------------------------------------------
    async def upload_batch(
        self,
        files: Iterable[UploadFile],
        *,
        batch_id: str | None = None,
        created_by: str | None = None,
    ) -> UploadResponse:
        batch_id = batch_id or new_batch_id()
        batch_dir = settings.batch_raw_dir(batch_id)

        # Persist batch row first so FK constraints succeed.
        if self.session.get(Batch, batch_id) is None:
            self.session.add(
                Batch(
                    batch_id=batch_id,
                    status="uploaded",
                    current_stage="uploaded",
                    created_by=created_by,
                )
            )
            self.session.flush()

        infos: list[UploadedFileInfo] = []
        total_bytes = 0

        for upload in files:
            if not upload.filename:
                raise ValidationError("Upload missing filename.")
            file_type = detect_file_format(upload.filename)
            if file_type == "unknown":
                raise FileFormatError(
                    f"Unsupported file type for '{upload.filename}'."
                )

            safe_name = safe_filename(upload.filename)
            file_id = new_file_id()
            stored_name = f"{file_id}__{safe_name}"
            stored_path = batch_dir / stored_name

            content = await upload.read()
            max_bytes = settings.max_upload_mb * 1024 * 1024
            if len(content) > max_bytes:
                raise ValidationError(
                    f"File '{upload.filename}' exceeds MAX_UPLOAD_MB="
                    f"{settings.max_upload_mb}MB."
                )
            stored_path.write_bytes(content)
            total_bytes += len(content)

            file_hash = hash_file_sha256(stored_path)
            row = UploadedFile(
                file_id=file_id,
                batch_id=batch_id,
                original_file_name=upload.filename,
                stored_file_path=str(stored_path),
                file_type=file_type,
                file_size=len(content),
                file_hash=file_hash,
                upload_time=datetime.utcnow(),
                status="uploaded",
            )
            self.session.add(row)

            infos.append(
                UploadedFileInfo(
                    file_id=file_id,
                    original_file_name=upload.filename,
                    stored_file_path=str(stored_path),
                    file_type=file_type,
                    file_size=len(content),
                    file_hash=file_hash,
                )
            )
            _log.info(
                "Stored upload batch=%s file=%s bytes=%d type=%s",
                batch_id, upload.filename, len(content), file_type,
            )

        self.session.commit()
        return UploadResponse(
            batch_id=batch_id,
            files=infos,
            total_files=len(infos),
            total_bytes=total_bytes,
        )

    # ------------------------------------------------------------------
    def list_files(self, batch_id: str) -> list[UploadedFile]:
        return (
            self.session.query(UploadedFile)
            .filter(UploadedFile.batch_id == batch_id)
            .order_by(UploadedFile.upload_time)
            .all()
        )

    def get_batch_dir(self, batch_id: str) -> Path:
        return settings.batch_raw_dir(batch_id)
