"""Tests for the pure-Python parts of the relationship detector."""

from __future__ import annotations

from app.services.relationship_detector_service import (
    _ColumnRef,
    _cardinality_score,
    _infer_relation_type,
    _is_id_name,
    _risk_assessment,
    _string_similarity,
    _types_compatible,
)


def _col(table: str, name: str, *, unique: int, rows: int, null_pct: float = 0,
         phys: str = "string") -> _ColumnRef:
    return _ColumnRef(
        table=table, column=name, original=name,
        physical_type=phys, semantic_type="id",
        null_percentage=null_pct, unique_count=unique, row_count=rows,
    )


def test_string_similarity_and_id_pattern() -> None:
    assert _string_similarity("customer_id", "customer_id") == 1.0
    assert _string_similarity("cust_id", "customer_id") > 0.6
    assert _is_id_name("customer_id")
    assert _is_id_name("رقم_العميل")
    assert not _is_id_name("description")


def test_types_compatible() -> None:
    assert _types_compatible("integer", "decimal")
    assert _types_compatible("string", "text")
    assert _types_compatible("integer", "string")  # codes-as-text scenario


def test_infer_relation_type_one_to_many() -> None:
    parent = _col("customers", "id", unique=1000, rows=1000)        # unique
    child = _col("orders", "customer_id", unique=400, rows=10000)   # non-unique
    rel = _infer_relation_type(parent, child)
    assert rel in {"one_to_many", "many_to_one"}


def test_risk_assessment_many_to_many() -> None:
    a = _col("a", "x", unique=10, rows=1000)
    b = _col("b", "x", unique=10, rows=1000)
    rel = _infer_relation_type(a, b)
    assert rel == "many_to_many"
    level, reasons = _risk_assessment(a, b, overlap=0.9, relation_type=rel)
    assert level == "high"
    assert "Many-to-many" in (reasons or "")


def test_cardinality_score_uses_max_uniqueness() -> None:
    a = _col("a", "x", unique=100, rows=100)   # 1.0
    b = _col("b", "x", unique=50, rows=100)    # 0.5
    assert _cardinality_score(a, b) == 1.0
