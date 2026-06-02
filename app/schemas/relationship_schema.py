"""Schemas for relationship detection output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RelationType = Literal[
    "one_to_one", "one_to_many", "many_to_one", "many_to_many", "unknown"
]
RiskLevel = Literal["none", "low", "medium", "high", "critical"]
SuggestionStatus = Literal["suggested", "approved", "rejected", "edited"]


class RelationshipScores(BaseModel):
    column_name_similarity_score: float = Field(ge=0, le=1)
    value_overlap_score: float = Field(ge=0, le=1)
    data_type_compatibility_score: float = Field(ge=0, le=1)
    cardinality_score: float = Field(ge=0, le=1)


class RelationshipSuggestion(BaseModel):
    suggestion_id: int
    batch_id: str

    source_table: str
    source_column: str
    source_original_column: str | None = None

    target_table: str
    target_column: str
    target_original_column: str | None = None

    suggested_relation_type: RelationType
    confidence_score: float = Field(ge=0, le=1)
    scores: RelationshipScores

    matching_values_count: int
    source_distinct_count: int
    target_distinct_count: int
    source_null_percentage: float = Field(ge=0, le=100)
    target_null_percentage: float = Field(ge=0, le=100)

    risk_level: RiskLevel
    risk_reason: str | None = None
    recommendation: str | None = None

    status: SuggestionStatus = "suggested"


class RelationshipSuggestionList(BaseModel):
    batch_id: str
    total: int
    suggestions: list[RelationshipSuggestion]
