"""Schemas for export-job responses."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

ExportTarget = Literal["powerbi", "zakaadash", "final_files", "sql", "all"]
ExportStatus = Literal["pending", "running", "completed", "failed"]


class ExportArtifact(BaseModel):
    name: str
    path: str
    size_bytes: int
    description: str | None = None


class ExportJobOut(BaseModel):
    job_id: int
    batch_id: str
    target: ExportTarget
    status: ExportStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    artifacts: list[ExportArtifact] = []
    message: str | None = None
