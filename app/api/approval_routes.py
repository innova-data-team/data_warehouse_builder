"""Approve / reject / edit relationship suggestions."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.database import get_metadata_session
from app.schemas.approval_schema import (
    ApprovalAction,
    ApprovedRelationshipOut,
    RelationshipEdit,
)
from app.services.relationship_approval_service import RelationshipApprovalService

router = APIRouter(prefix="/pipeline", tags=["approvals"])


def _to_schema(o) -> ApprovedRelationshipOut:
    return ApprovedRelationshipOut(
        approved_id=o.id,
        suggestion_id=o.suggestion_id or 0,
        batch_id=o.batch_id,
        source_table=o.source_table,
        source_column=o.source_column,
        target_table=o.target_table,
        target_column=o.target_column,
        relation_type=o.relation_type,
        decided_by=o.decided_by,
        note=o.note,
    )


@router.post(
    "/{batch_id}/relationships/{suggestion_id}/approve",
    response_model=ApprovedRelationshipOut,
)
def approve(
    batch_id: str,
    suggestion_id: int,
    payload: ApprovalAction = Body(default_factory=ApprovalAction),
    decided_by: str | None = None,
    session: Session = Depends(get_metadata_session),
) -> ApprovedRelationshipOut:
    out = RelationshipApprovalService(session).approve(
        batch_id, suggestion_id, decided_by=decided_by, note=payload.note,
    )
    return _to_schema(out)


@router.post("/{batch_id}/relationships/{suggestion_id}/reject")
def reject(
    batch_id: str,
    suggestion_id: int,
    payload: ApprovalAction = Body(default_factory=ApprovalAction),
    decided_by: str | None = None,
    session: Session = Depends(get_metadata_session),
) -> dict[str, str]:
    RelationshipApprovalService(session).reject(
        batch_id, suggestion_id, decided_by=decided_by, note=payload.note,
    )
    return {"status": "rejected"}


@router.put(
    "/{batch_id}/relationships/{suggestion_id}/edit",
    response_model=ApprovedRelationshipOut,
)
def edit(
    batch_id: str,
    suggestion_id: int,
    payload: RelationshipEdit,
    decided_by: str | None = None,
    session: Session = Depends(get_metadata_session),
) -> ApprovedRelationshipOut:
    out = RelationshipApprovalService(session).edit(
        batch_id, suggestion_id, payload=payload, decided_by=decided_by,
    )
    return _to_schema(out)
