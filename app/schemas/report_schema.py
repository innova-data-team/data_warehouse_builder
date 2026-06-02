"""Schemas for quality / data-dictionary / lineage report responses."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Severity = Literal["Critical", "High", "Medium", "Low", "Info"]


class QualityIssueOut(BaseModel):
    issue_id: int
    batch_id: str
    layer: Literal["bronze", "silver", "gold", "metadata"]
    table_name: str
    column_name: str | None = None
    issue_type: str
    severity: Severity
    issue_description: str
    affected_rows_count: int = 0
    affected_rows_percentage: float = 0.0
    sample_values: list[str] = []
    suggested_fix: str | None = None
    auto_fix_available: bool = False
    auto_fix_applied: bool = False


class QualityReport(BaseModel):
    batch_id: str
    total_issues: int
    by_severity: dict[Severity, int]
    issues: list[QualityIssueOut]


class ColumnDictionaryEntry(BaseModel):
    table_name: str
    column_name: str
    original_name: str | None = None
    physical_type: str
    semantic_type: str
    null_percentage: float
    sample_values: list[str] = []
    is_arabic: bool = False
    description_en: str | None = None
    description_ar: str | None = None


class DataDictionary(BaseModel):
    batch_id: str
    total_columns: int
    columns: list[ColumnDictionaryEntry]


class LineageEdge(BaseModel):
    from_layer: str
    from_object: str
    to_layer: str
    to_object: str
    relation: str = "derived_from"


class LineageReport(BaseModel):
    batch_id: str
    edges: list[LineageEdge]
