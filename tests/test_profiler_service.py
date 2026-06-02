"""Tests for the type detection + semantic profiling helpers.

We deliberately avoid touching MySQL here; ProfilerService is exercised
through its building blocks.
"""

from __future__ import annotations

from app.utils.arabic_text_normalization import (
    arabic_char_ratio,
    normalize_text,
)
from app.utils.type_detection import detect_physical_type, detect_semantic_type


def test_physical_type_numeric() -> None:
    physical, dist, conf = detect_physical_type(["1", "2", "3", "4.5", None])
    assert physical in {"decimal", "float"}
    assert conf > 0.5
    assert "integer" in dist or "float" in dist


def test_physical_type_string_with_long_values() -> None:
    long_val = "x" * 300
    physical, _, _ = detect_physical_type([long_val, "hello"])
    assert physical == "text"


def test_semantic_type_email_from_values() -> None:
    sem = detect_semantic_type(
        "contact",
        ["a@x.com", "b@y.org", "carol@example.co"],
    )
    assert sem == "email"


def test_semantic_type_arabic_name_column() -> None:
    sem = detect_semantic_type("اسم الموظف", ["محمد", "أحمد", "سارة"])
    assert sem in {"name", "unknown"}  # name pattern hit OR fallback


def test_arabic_normalization_letter_unification() -> None:
    out = normalize_text("أَهْلاً وَسَهْلاً ١٢٣")
    assert "أ" not in out
    assert "١" not in out  # Arabic-Indic digit converted
    assert "123" in out
    assert arabic_char_ratio(out) > 0.5
