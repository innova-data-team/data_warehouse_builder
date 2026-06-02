"""ORM model: ``approved_relationships`` — only these feed the Gold builder."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ApprovedRelationship(Base):
    __tablename__ = "approved_relationships"
    __table_args__ = (
        Index("ix_approved_rel_batch", "batch_id"),
        Index("ix_approved_rel_source", "source_table", "source_column"),
        Index("ix_approved_rel_target", "target_table", "target_column"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("batches.batch_id"), nullable=False
    )
    suggestion_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("relationship_suggestions.id"), nullable=True
    )

    source_table: Mapped[str] = mapped_column(String(128), nullable=False)
    source_column: Mapped[str] = mapped_column(String(128), nullable=False)
    target_table: Mapped[str] = mapped_column(String(128), nullable=False)
    target_column: Mapped[str] = mapped_column(String(128), nullable=False)

    relation_type: Mapped[str] = mapped_column(String(16), nullable=False)

    decided_by: Mapped[str | None] = mapped_column(String(128))
    note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
