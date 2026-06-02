"""Schemas for the relationship approval workflow."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .relationship_schema import RelationType


class ApprovalAction(BaseModel):
    """Body for ``POST /relationships/{id}/approve|reject``."""

    note: str | None = Field(default=None, max_length=500)


class RelationshipEdit(BaseModel):
    """Body for ``PUT /relationships/{id}/edit``."""

    suggested_relation_type: RelationType | None = None
    target_table: str | None = None
    target_column: str | None = None
    source_table: str | None = None
    source_column: str | None = None
    note: str | None = Field(default=None, max_length=500)


class ApprovedRelationshipOut(BaseModel):
    approved_id: int
    suggestion_id: int
    batch_id: str
    source_table: str
    source_column: str
    target_table: str
    target_column: str
    relation_type: RelationType
    decided_by: str | None = None
    note: str | None = None
