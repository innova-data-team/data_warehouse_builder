"""Tests for the SQL safety helpers and Bronze SQL renderer."""

from __future__ import annotations

from app.services.bronze_service import BronzeService
from app.utils.sql_utils import (
    is_reserved_word,
    quote_identifier,
    safe_column_name,
    safe_table_name,
)


def test_quote_identifier_escapes_backticks() -> None:
    assert quote_identifier("col") == "`col`"
    assert quote_identifier("we`ird") == "`we``ird`"


def test_safe_table_name_handles_arabic_and_reserved() -> None:
    out = safe_table_name("Order")  # SQL reserved
    assert is_reserved_word("order")
    assert out != "order"
    assert "_" in out  # got the reserved-word suffix


def test_safe_column_name_truncates_with_hash() -> None:
    long_name = "a" * 200
    safe = safe_column_name(long_name)
    assert len(safe) <= 64
    safe2 = safe_column_name("b" * 200)
    assert safe != safe2  # hashes differ → no collision


def test_safe_column_name_leading_digit() -> None:
    assert safe_column_name("1st_col").startswith("col_")


def test_render_insert_sql_handles_nulls_and_quotes() -> None:
    sql = BronzeService.render_insert_sql(
        "bronze_t", ["a", "b"],
        [("hello", None), ("O'Hara", "x")],
    )
    assert sql.startswith("INSERT INTO `bronze_t`")
    assert "NULL" in sql
    assert "'O''Hara'" in sql
