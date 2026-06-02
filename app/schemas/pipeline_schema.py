"""Schemas for pipeline orchestration and per-layer status responses."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

PipelineStage = Literal[
    "uploaded",
    "bronze_loading",
    "bronze_done",
    "profiling",
    "profiling_done",
    "silver_building",
    "silver_done",
    "relationships_detected",
    "awaiting_approval",
    "gold_building",
    "gold_done",
    "exporting",
    "completed",
    "failed",
]


class PipelineStageResult(BaseModel):
    stage: PipelineStage
    started_at: datetime
    finished_at: datetime | None = None
    success: bool = True
    message: str | None = None
    artifacts: dict[str, str] = {}   # logical-name -> path / table name


class PipelineStatus(BaseModel):
    batch_id: str
    current_stage: PipelineStage
    stages: list[PipelineStageResult]
    bronze_tables: list[str] = []
    silver_tables: list[str] = []
    gold_tables: list[str] = []
    gold_views: list[str] = []
    suggestion_count: int = 0
    approved_count: int = 0
    quality_issue_count: int = 0


class BronzeTableInfo(BaseModel):
    table_name: str
    source_file: str
    source_sheet: str | None = None
    row_count: int
    column_count: int


class SilverTableInfo(BaseModel):
    table_name: str
    source_bronze_table: str
    row_count: int
    column_count: int
    quality_score: float | None = None
