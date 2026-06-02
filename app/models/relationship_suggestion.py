"""ORM model: ``relationship_suggestions``."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RelationshipSuggestion(Base):
    __tablename__ = "relationship_suggestions"
    __table_args__ = (
        Index("ix_rel_sugg_batch", "batch_id"),
        Index("ix_rel_sugg_status", "status"),
        Index("ix_rel_sugg_source", "source_table", "source_column"),
        Index("ix_rel_sugg_target", "target_table", "target_column"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("batches.batch_id"), nullable=False
    )

    source_table: Mapped[str] = mapped_column(String(128), nullable=False)
    source_column: Mapped[str] = mapped_column(String(128), nullable=False)
    source_original_column: Mapped[str | None] = mapped_column(String(512))

    target_table: Mapped[str] = mapped_column(String(128), nullable=False)
    target_column: Mapped[str] = mapped_column(String(128), nullable=False)
    target_original_column: Mapped[str | None] = mapped_column(String(512))

    suggested_relation_type: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)

    column_name_similarity_score: Mapped[float] = mapped_column(Float, default=0.0)
    value_overlap_score: Mapped[float] = mapped_column(Float, default=0.0)
    data_type_compatibility_score: Mapped[float] = mapped_column(Float, default=0.0)
    cardinality_score: Mapped[float] = mapped_column(Float, default=0.0)

    matching_values_count: Mapped[int] = mapped_column(BigInteger, default=0)
    source_distinct_count: Mapped[int] = mapped_column(BigInteger, default=0)
    target_distinct_count: Mapped[int] = mapped_column(BigInteger, default=0)
    source_null_percentage: Mapped[float] = mapped_column(Float, default=0.0)
    target_null_percentage: Mapped[float] = mapped_column(Float, default=0.0)

    risk_level: Mapped[str] = mapped_column(String(16), default="none")
    risk_reason: Mapped[str | None] = mapped_column(Text)
    recommendation: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(16), default="suggested", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
