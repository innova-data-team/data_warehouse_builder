"""ORM model: ``quality_issues``."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class QualityIssue(Base):
    __tablename__ = "quality_issues"
    __table_args__ = (
        Index("ix_quality_issues_batch", "batch_id"),
        Index("ix_quality_issues_severity", "severity"),
        Index("ix_quality_issues_table", "table_name"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("batches.batch_id"), nullable=False
    )
    layer: Mapped[str] = mapped_column(String(16), nullable=False)
    table_name: Mapped[str] = mapped_column(String(128), nullable=False)
    column_name: Mapped[str | None] = mapped_column(String(128))

    issue_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    issue_description: Mapped[str] = mapped_column(Text, nullable=False)

    affected_rows_count: Mapped[int] = mapped_column(BigInteger, default=0)
    affected_rows_percentage: Mapped[float] = mapped_column(Float, default=0.0)
    sample_values_json: Mapped[str | None] = mapped_column(Text)

    suggested_fix: Mapped[str | None] = mapped_column(Text)
    auto_fix_available: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_fix_applied: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
