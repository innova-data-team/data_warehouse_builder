"""ORM model: ``silver_tables``."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SilverTable(Base):
    __tablename__ = "silver_tables"
    __table_args__ = (
        Index("ix_silver_tables_batch", "batch_id"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("batches.batch_id"), nullable=False
    )
    bronze_table_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bronze_tables.id"), nullable=False
    )
    table_name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    row_count: Mapped[int] = mapped_column(BigInteger, default=0)
    column_count: Mapped[int] = mapped_column(BigInteger, default=0)
    dedup_removed_rows: Mapped[int] = mapped_column(BigInteger, default=0)
    quality_score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
