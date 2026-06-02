"""ORM model: ``column_profiles`` — per-column profiling + semantic type."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ColumnProfile(Base):
    __tablename__ = "column_profiles"
    __table_args__ = (
        Index("ix_column_profiles_batch", "batch_id"),
        Index("ix_column_profiles_table_col", "table_name", "column_name"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("batches.batch_id"), nullable=False
    )
    layer: Mapped[str] = mapped_column(String(16), nullable=False)
    table_name: Mapped[str] = mapped_column(String(128), nullable=False)

    column_name: Mapped[str] = mapped_column(String(128), nullable=False)
    original_column_name: Mapped[str | None] = mapped_column(String(512))

    physical_type: Mapped[str] = mapped_column(String(32), nullable=False)
    semantic_type: Mapped[str] = mapped_column(String(32), nullable=False)
    type_confidence: Mapped[float | None] = mapped_column(Float)

    null_count: Mapped[int] = mapped_column(BigInteger, default=0)
    null_percentage: Mapped[float] = mapped_column(Float, default=0.0)
    empty_string_count: Mapped[int] = mapped_column(BigInteger, default=0)
    unique_count: Mapped[int] = mapped_column(BigInteger, default=0)
    uniqueness_ratio: Mapped[float] = mapped_column(Float, default=0.0)

    min_value: Mapped[str | None] = mapped_column(String(512))
    max_value: Mapped[str | None] = mapped_column(String(512))
    mean_value: Mapped[float | None] = mapped_column(Float)
    median_value: Mapped[float | None] = mapped_column(Float)
    stddev_value: Mapped[float | None] = mapped_column(Float)

    top_values_json: Mapped[str | None] = mapped_column(Text)
    sample_values_json: Mapped[str | None] = mapped_column(Text)

    invalid_value_count: Mapped[int] = mapped_column(BigInteger, default=0)
    arabic_text_percentage: Mapped[float] = mapped_column(Float, default=0.0)
    english_text_percentage: Mapped[float] = mapped_column(Float, default=0.0)
    numeric_text_percentage: Mapped[float] = mapped_column(Float, default=0.0)
    date_text_percentage: Mapped[float] = mapped_column(Float, default=0.0)
    percentage_text_percentage: Mapped[float] = mapped_column(Float, default=0.0)
    currency_text_percentage: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
