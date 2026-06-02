"""Approve / reject / edit relationship suggestions."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models import ApprovedRelationship, RelationshipSuggestion
from app.schemas.approval_schema import RelationshipEdit

_log = get_logger(__name__)


class RelationshipApprovalService:
    """All write-side state transitions for the approval workflow."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    def list_suggestions(self, batch_id: str) -> list[RelationshipSuggestion]:
        return (
            self.session.query(RelationshipSuggestion)
            .filter(RelationshipSuggestion.batch_id == batch_id)
            .order_by(RelationshipSuggestion.confidence_score.desc())
            .all()
        )

    def list_approved(self, batch_id: str) -> list[ApprovedRelationship]:
        return (
            self.session.query(ApprovedRelationship)
            .filter(ApprovedRelationship.batch_id == batch_id)
            .order_by(ApprovedRelationship.decided_at)
            .all()
        )

    # ------------------------------------------------------------------
    def approve(
        self, batch_id: str, suggestion_id: int, *, decided_by: str | None, note: str | None
    ) -> ApprovedRelationship:
        sug = self._get(batch_id, suggestion_id)
        sug.status = "approved"
        approved = ApprovedRelationship(
            batch_id=batch_id,
            suggestion_id=sug.id,
            source_table=sug.source_table,
            source_column=sug.source_column,
            target_table=sug.target_table,
            target_column=sug.target_column,
            relation_type=sug.suggested_relation_type,
            decided_by=decided_by,
            note=note,
        )
        self.session.add(approved)
        self.session.commit()
        _log.info("Approved suggestion id=%s batch=%s", suggestion_id, batch_id)
        return approved

    def reject(
        self, batch_id: str, suggestion_id: int, *, decided_by: str | None, note: str | None
    ) -> RelationshipSuggestion:
        sug = self._get(batch_id, suggestion_id)
        sug.status = "rejected"
        sug.recommendation = (
            (sug.recommendation or "") + f"\n[Rejected by {decided_by or 'user'}] {note or ''}"
        ).strip()
        self.session.commit()
        return sug

    def edit(
        self,
        batch_id: str,
        suggestion_id: int,
        *,
        payload: RelationshipEdit,
        decided_by: str | None,
    ) -> ApprovedRelationship:
        sug = self._get(batch_id, suggestion_id)
        # Apply overrides to a fresh ApprovedRelationship row.
        merged = {
            "source_table": payload.source_table or sug.source_table,
            "source_column": payload.source_column or sug.source_column,
            "target_table": payload.target_table or sug.target_table,
            "target_column": payload.target_column or sug.target_column,
            "relation_type": payload.suggested_relation_type or sug.suggested_relation_type,
        }
        for key in ("source_table", "source_column", "target_table", "target_column"):
            if not merged[key]:
                raise ValidationError(f"Missing required field after edit: {key}")

        sug.status = "edited"
        approved = ApprovedRelationship(
            batch_id=batch_id,
            suggestion_id=sug.id,
            decided_by=decided_by,
            note=payload.note,
            **merged,
        )
        self.session.add(approved)
        self.session.commit()
        return approved

    # ------------------------------------------------------------------
    def _get(self, batch_id: str, suggestion_id: int) -> RelationshipSuggestion:
        sug = (
            self.session.query(RelationshipSuggestion)
            .filter(
                RelationshipSuggestion.id == suggestion_id,
                RelationshipSuggestion.batch_id == batch_id,
            )
            .one_or_none()
        )
        if sug is None:
            raise NotFoundError(
                f"Suggestion id={suggestion_id} not found in batch {batch_id}."
            )
        return sug
