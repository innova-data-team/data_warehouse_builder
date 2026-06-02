"""ORM model: ``bronze_tables`` — registry of created Bronze MySQL tables."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BronzeTable(Base):
    __tablename__ = "bronze_tables"
    __table_args__ = (
        Index("ix_bronze_tables_batch", "batch_id"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("batches.batch_id"), nullable=False
    )
    file_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("uploaded_files.file_id"), nullable=False
    )
    table_name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    source_file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    source_sheet_name: Mapped[str | None] = mapped_column(String(256))
    row_count: Mapped[int] = mapped_column(BigInteger, default=0)
    column_count: Mapped[int] = mapped_column(BigInteger, default=0)
    failed_row_count: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
