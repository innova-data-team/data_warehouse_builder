"""Relationship-detection endpoints (separate from the approval workflow)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_metadata_session
from app.schemas.relationship_schema import (
    RelationshipScores,
    RelationshipSuggestion,
    RelationshipSuggestionList,
)
from app.services.relationship_approval_service import RelationshipApprovalService
from app.services.relationship_detector_service import RelationshipDetectorService

router = APIRouter(prefix="/pipeline", tags=["relationships"])


def _to_schema(orm) -> RelationshipSuggestion:
    return RelationshipSuggestion(
        suggestion_id=orm.id,
        batch_id=orm.batch_id,
        source_table=orm.source_table,
        source_column=orm.source_column,
        source_original_column=orm.source_original_column,
        target_table=orm.target_table,
        target_column=orm.target_column,
        target_original_column=orm.target_original_column,
        suggested_relation_type=orm.suggested_relation_type,
        confidence_score=orm.confidence_score,
        scores=RelationshipScores(
            column_name_similarity_score=orm.column_name_similarity_score or 0.0,
            value_overlap_score=orm.value_overlap_score or 0.0,
            data_type_compatibility_score=orm.data_type_compatibility_score or 0.0,
            cardinality_score=orm.cardinality_score or 0.0,
        ),
        matching_values_count=orm.matching_values_count or 0,
        source_distinct_count=orm.source_distinct_count or 0,
        target_distinct_count=orm.target_distinct_count or 0,
        source_null_percentage=orm.source_null_percentage or 0.0,
        target_null_percentage=orm.target_null_percentage or 0.0,
        risk_level=orm.risk_level or "none",
        risk_reason=orm.risk_reason,
        recommendation=orm.recommendation,
        status=orm.status,
    )


@router.post(
    "/{batch_id}/relationships/detect",
    response_model=RelationshipSuggestionList,
)
def detect_relationships(
    batch_id: str,
    session: Session = Depends(get_metadata_session),
) -> RelationshipSuggestionList:
    service = RelationshipDetectorService(session)
    service.detect(batch_id)
    suggestions = RelationshipApprovalService(session).list_suggestions(batch_id)
    return RelationshipSuggestionList(
        batch_id=batch_id,
        total=len(suggestions),
        suggestions=[_to_schema(s) for s in suggestions],
    )


@router.get(
    "/{batch_id}/relationships/suggestions",
    response_model=RelationshipSuggestionList,
)
def list_suggestions(
    batch_id: str,
    session: Session = Depends(get_metadata_session),
) -> RelationshipSuggestionList:
    suggestions = RelationshipApprovalService(session).list_suggestions(batch_id)
    return RelationshipSuggestionList(
        batch_id=batch_id,
        total=len(suggestions),
        suggestions=[_to_schema(s) for s in suggestions],
    )
