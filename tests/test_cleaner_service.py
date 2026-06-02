"""Tests for the per-column cleaning routines."""

from __future__ import annotations

from datetime import datetime

from app.services.cleaner_service import clean_column
from app.utils.number_utils import parse_number, parse_percentage


def test_clean_arabic_amount_column() -> None:
    values = ["١٬٠٠٠", "2,500.50", " 3000 ", None, "غير متوفر"]
    out, stats = clean_column(
        "total_amount", values, physical_type="decimal", semantic_type="amount",
    )
    assert out[0] == 1000
    assert float(out[1]) == 2500.50
    assert float(out[2]) == 3000
    assert out[3] is None
    assert out[4] is None     # null-like Arabic token
    assert stats.rows_null_normalized == 2  # explicit None + "غير متوفر"


def test_parse_percentage_variants() -> None:
    assert parse_percentage("5%") == parse_percentage("0.05")
    assert parse_percentage("٥٪") == parse_percentage("5%")
    assert parse_percentage("7") == parse_percentage("0.07")


def test_clean_date_column() -> None:
    values = ["2026-04-15", "15/04/2026", "31-01-2024", "garbage"]
    out, stats = clean_column(
        "visit_date", values, physical_type="date", semantic_type="date",
    )
    assert isinstance(out[0], datetime)
    assert isinstance(out[1], datetime)
    assert out[1].day == 15 and out[1].month == 4
    assert out[3] is None
    assert stats.rows_failed_conversion == 1
