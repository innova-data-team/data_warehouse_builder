"""Schemas for the file upload API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class UploadedFileInfo(BaseModel):
    file_id: str
    original_file_name: str
    stored_file_path: str
    file_type: Literal["csv", "excel", "json", "unknown"]
    file_size: int
    file_hash: str
    detected_encoding: str | None = None
    detected_delimiter: str | None = None
    sheet_count: int | None = None
    row_count: int | None = None
    column_count: int | None = None


class UploadResponse(BaseModel):
    batch_id: str
    files: list[UploadedFileInfo]
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)
    total_files: int
    total_bytes: int
