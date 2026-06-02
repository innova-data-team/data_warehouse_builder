"""ORM model: ``table_profiles``."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TableProfile(Base):
    __tablename__ = "table_profiles"
    __table_args__ = (
        Index("ix_table_profiles_batch", "batch_id"),
        Index("ix_table_profiles_table", "table_name"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("batches.batch_id"), nullable=False
    )
    layer: Mapped[str] = mapped_column(String(16), nullable=False)  # bronze|silver|gold
    table_name: Mapped[str] = mapped_column(String(128), nullable=False)
    row_count: Mapped[int] = mapped_column(BigInteger, default=0)
    column_count: Mapped[int] = mapped_column(BigInteger, default=0)
    duplicate_row_count: Mapped[int] = mapped_column(BigInteger, default=0)
    empty_row_count: Mapped[int] = mapped_column(BigInteger, default=0)
    memory_bytes: Mapped[int | None] = mapped_column(BigInteger)
    source_file: Mapped[str | None] = mapped_column(String(512))
    source_sheet: Mapped[str | None] = mapped_column(String(256))
    candidate_primary_keys: Mapped[str | None] = mapped_column(Text)  # JSON list
    classification: Mapped[str | None] = mapped_column(String(32))    # fact / dim / bridge / flat
    quality_score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
