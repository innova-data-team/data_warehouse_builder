"""Suggests relationships between Silver tables.

For every cross-table pair of columns ``(A.col_a, B.col_b)``, computes a
weighted confidence score from five signals:

    1. Name similarity (safe + original)        — 0.20 + 0.10
    2. Data-type compatibility                  — 0.15
    3. Value overlap ratio (Jaccard-ish)        — 0.30
    4. Cardinality compatibility                — 0.10
    5. Business-name pattern bonus              — 0.05

Pairs above the configured thresholds are written to
``relationship_suggestions`` for human approval.

The detector also infers ``relation_type`` and attaches risk warnings
(many-to-many, weak overlap, nullable FK, type coercion, etc.).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Sequence

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import silver_engine
from app.core.logging import get_logger
from app.models import ColumnProfile, RelationshipSuggestion, TableProfile
from app.utils.arabic_text_normalization import normalize_text
from app.utils.sql_utils import quote_identifier

_log = get_logger(__name__)

_NUMERIC_TYPES = {"integer", "float", "decimal"}
_STRING_TYPES = {"string", "text"}
_ID_NAME_PATTERNS = (
    "id", "code", "number", "no", "key", "رقم", "كود", "معرف",
)


@dataclass(slots=True)
class _ColumnRef:
    table: str
    column: str
    original: str | None
    physical_type: str
    semantic_type: str
    null_percentage: float
    unique_count: int
    row_count: int

    @property
    def uniqueness_ratio(self) -> float:
        return (self.unique_count / self.row_count) if self.row_count else 0.0


# ---------------------------------------------------------------------------
class RelationshipDetectorService:
    """Score and persist candidate relationships."""

    def __init__(
        self,
        session: Session,
        *,
        min_confidence: float | None = None,
        value_overlap_threshold: float | None = None,
    ) -> None:
        self.session = session
        self.engine: Engine = silver_engine()
        self.min_confidence = (
            min_confidence if min_confidence is not None else settings.relationship_min_confidence
        )
        self.overlap_threshold = (
            value_overlap_threshold
            if value_overlap_threshold is not None
            else settings.relationship_value_overlap_threshold
        )

    # ------------------------------------------------------------------
    def detect(self, batch_id: str) -> list[RelationshipSuggestion]:
        cols = self._load_silver_columns(batch_id)
        if len(cols) < 2:
            return []

        suggestions: list[RelationshipSuggestion] = []
        for i, a in enumerate(cols):
            for b in cols[i + 1 :]:
                if a.table == b.table:
                    continue
                if not _types_compatible(a.physical_type, b.physical_type):
                    continue
                pair = self._score_pair(a, b)
                if pair is None:
                    continue
                suggestions.append(pair)

        self.session.add_all(
            [
                RelationshipSuggestion(
                    batch_id=batch_id,
                    source_table=s.source_table,
                    source_column=s.source_column,
                    source_original_column=s.source_original_column,
                    target_table=s.target_table,
                    target_column=s.target_column,
                    target_original_column=s.target_original_column,
                    suggested_relation_type=s.suggested_relation_type,
                    confidence_score=s.confidence_score,
                    column_name_similarity_score=s.column_name_similarity_score,
                    value_overlap_score=s.value_overlap_score,
                    data_type_compatibility_score=s.data_type_compatibility_score,
                    cardinality_score=s.cardinality_score,
                    matching_values_count=s.matching_values_count,
                    source_distinct_count=s.source_distinct_count,
                    target_distinct_count=s.target_distinct_count,
                    source_null_percentage=s.source_null_percentage,
                    target_null_percentage=s.target_null_percentage,
                    risk_level=s.risk_level,
                    risk_reason=s.risk_reason,
                    recommendation=s.recommendation,
                    status="suggested",
                )
                for s in suggestions
            ]
        )
        self.session.commit()
        _log.info("Detected %d relationship suggestions for batch=%s",
                  len(suggestions), batch_id)
        return suggestions

    # ------------------------------------------------------------------
    def _load_silver_columns(self, batch_id: str) -> list[_ColumnRef]:
        rows = (
            self.session.query(ColumnProfile)
            .filter(ColumnProfile.batch_id == batch_id, ColumnProfile.layer == "silver")
            .all()
        )
        tables = {
            t.table_name: t.row_count
            for t in self.session.query(TableProfile)
            .filter(TableProfile.batch_id == batch_id, TableProfile.layer == "silver")
            .all()
        }
        return [
            _ColumnRef(
                table=r.table_name,
                column=r.column_name,
                original=r.original_column_name,
                physical_type=r.physical_type,
                semantic_type=r.semantic_type,
                null_percentage=r.null_percentage or 0.0,
                unique_count=r.unique_count or 0,
                row_count=tables.get(r.table_name, 0),
            )
            for r in rows
            if not r.column_name.startswith("_")
        ]

    # ------------------------------------------------------------------
    def _score_pair(self, a: _ColumnRef, b: _ColumnRef) -> RelationshipSuggestion | None:
        name_sim = max(
            _string_similarity(a.column, b.column),
            _string_similarity(a.column.rstrip("0123456789"), b.column.rstrip("0123456789")),
        )
        orig_sim = 0.0
        if a.original and b.original:
            orig_sim = _string_similarity(
                normalize_text(a.original).lower(),
                normalize_text(b.original).lower(),
            )
        type_compat = 1.0 if _types_compatible(a.physical_type, b.physical_type) else 0.0
        overlap, matching, distinct_a, distinct_b = self._value_overlap(a, b)
        cardinality_score = _cardinality_score(a, b)
        pattern_bonus = 1.0 if (_is_id_name(a.column) and _is_id_name(b.column)) else 0.0

        confidence = (
            0.20 * name_sim
            + 0.10 * orig_sim
            + 0.15 * type_compat
            + 0.30 * overlap
            + 0.10 * cardinality_score
            + 0.05 * pattern_bonus
        )
        confidence = max(0.0, min(1.0, confidence))

        if confidence < self.min_confidence or overlap < self.overlap_threshold:
            return None

        relation_type = _infer_relation_type(a, b)
        risk_level, risk_reason = _risk_assessment(a, b, overlap, relation_type)
        recommendation = _recommendation(relation_type, risk_level)

        # Orient (source, target) so that the side with the higher
        # uniqueness ratio is the **target** (the dimension side).
        if b.uniqueness_ratio >= a.uniqueness_ratio:
            src, tgt = a, b
        else:
            src, tgt = b, a

        return RelationshipSuggestion(
            id=0, batch_id="placeholder",
            source_table=src.table, source_column=src.column,
            source_original_column=src.original,
            target_table=tgt.table, target_column=tgt.column,
            target_original_column=tgt.original,
            suggested_relation_type=relation_type,
            confidence_score=confidence,
            column_name_similarity_score=name_sim,
            value_overlap_score=overlap,
            data_type_compatibility_score=type_compat,
            cardinality_score=cardinality_score,
            matching_values_count=matching,
            source_distinct_count=distinct_a if src is a else distinct_b,
            target_distinct_count=distinct_b if tgt is b else distinct_a,
            source_null_percentage=src.null_percentage,
            target_null_percentage=tgt.null_percentage,
            risk_level=risk_level,
            risk_reason=risk_reason,
            recommendation=recommendation,
        )

    # ------------------------------------------------------------------
    def _value_overlap(self, a: _ColumnRef, b: _ColumnRef) -> tuple[float, int, int, int]:
        """Compute a value-overlap ratio using SQL set arithmetic in MySQL.

        Returns ``(overlap, matching_count, distinct_a, distinct_b)``.
        ``overlap`` is matching / min(distinct_a, distinct_b)  ∈ [0, 1].
        """
        q = text(
            f"""
            SELECT
                (SELECT COUNT(DISTINCT {quote_identifier(a.column)})
                   FROM {quote_identifier(a.table)}
                  WHERE {quote_identifier(a.column)} IS NOT NULL) AS dist_a,
                (SELECT COUNT(DISTINCT {quote_identifier(b.column)})
                   FROM {quote_identifier(b.table)}
                  WHERE {quote_identifier(b.column)} IS NOT NULL) AS dist_b,
                (SELECT COUNT(*) FROM (
                    SELECT DISTINCT CAST({quote_identifier(a.column)} AS CHAR(255)) AS v
                      FROM {quote_identifier(a.table)}
                     WHERE {quote_identifier(a.column)} IS NOT NULL
                ) ax
                INNER JOIN (
                    SELECT DISTINCT CAST({quote_identifier(b.column)} AS CHAR(255)) AS v
                      FROM {quote_identifier(b.table)}
                     WHERE {quote_identifier(b.column)} IS NOT NULL
                ) bx ON ax.v = bx.v) AS matching
            """
        )
        try:
            with self.engine.connect() as conn:
                row = conn.execute(q).mappings().one()
        except Exception as exc:  # noqa: BLE001
            _log.debug("Value-overlap query failed for %s.%s vs %s.%s: %s",
                       a.table, a.column, b.table, b.column, exc)
            return 0.0, 0, a.unique_count, b.unique_count

        dist_a = int(row["dist_a"] or 0)
        dist_b = int(row["dist_b"] or 0)
        matching = int(row["matching"] or 0)
        denom = min(dist_a, dist_b) or 1
        return min(1.0, matching / denom), matching, dist_a, dist_b


# ---------------------------------------------------------------------------
# Pure helpers (no DB)
# ---------------------------------------------------------------------------
def _string_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(a=a.lower(), b=b.lower()).ratio()


def _is_id_name(name: str) -> bool:
    n = name.lower()
    return any(p in n for p in _ID_NAME_PATTERNS) or n.endswith("_id") or n.endswith("id")


def _types_compatible(a: str, b: str) -> bool:
    if a == b:
        return True
    if a in _NUMERIC_TYPES and b in _NUMERIC_TYPES:
        return True
    if a in _STRING_TYPES and b in _STRING_TYPES:
        return True
    # Numeric ↔ string is sometimes valid (codes stored as text) but we
    # require strong value overlap; mark compatible at half strength.
    if (a in _NUMERIC_TYPES and b in _STRING_TYPES) or (b in _NUMERIC_TYPES and a in _STRING_TYPES):
        return True
    return False


def _cardinality_score(a: _ColumnRef, b: _ColumnRef) -> float:
    # Higher when at least one side is highly unique.
    return max(a.uniqueness_ratio, b.uniqueness_ratio)


def _infer_relation_type(a: _ColumnRef, b: _ColumnRef) -> str:
    a_unique = a.uniqueness_ratio >= 0.99
    b_unique = b.uniqueness_ratio >= 0.99
    if a_unique and b_unique:
        return "one_to_one"
    if a_unique and not b_unique:
        return "one_to_many"
    if b_unique and not a_unique:
        return "many_to_one"
    return "many_to_many"


def _risk_assessment(
    a: _ColumnRef, b: _ColumnRef, overlap: float, relation_type: str
) -> tuple[str, str | None]:
    reasons: list[str] = []
    level = "none"

    if relation_type == "many_to_many":
        level = "high"
        reasons.append("Many-to-many relation will explode rows after joining.")
    if relation_type in ("one_to_many", "many_to_one"):
        reasons.append("Measure-duplication risk if parent-side aggregates are joined.")
        if level == "none":
            level = "medium"
    if overlap < 0.7:
        reasons.append(f"Weak value overlap ({overlap:.0%}).")
        if level == "none":
            level = "low"
    if max(a.null_percentage, b.null_percentage) > 30:
        reasons.append("FK side has high null percentage (>30%).")
        if level == "none":
            level = "medium"
    if a.physical_type != b.physical_type:
        reasons.append("Type coercion required (different physical types).")
        if level == "none":
            level = "low"

    return level, "; ".join(reasons) if reasons else None


def _recommendation(relation_type: str, risk_level: str) -> str:
    if relation_type == "many_to_many":
        return "Introduce a bridge table; do not join directly in Gold."
    if relation_type in ("one_to_many", "many_to_one"):
        if risk_level in ("medium", "high"):
            return "Aggregate the many side by FK before joining."
        return "Safe to join in Gold using the many side as the fact."
    if relation_type == "one_to_one":
        return "Merge tables or keep as 1:1 lookup; safe to join."
    return "Review manually."
