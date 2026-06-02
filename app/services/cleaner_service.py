"""Per-column cleaning routines used by the Silver builder.

The cleaner is **stateless and pure**. It takes a raw column (list of
strings, the way Bronze stores them) and returns a typed list along with
a per-column ``CleaningStats`` report. The Silver builder then assembles
these into the final Silver frame.

Every transformation rule is logged so the caller can persist them as
``QualityIssue`` rows (with ``auto_fix_applied=True``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.utils.arabic_text_normalization import (
    normalize_text,
    try_fix_broken_arabic,
)
from app.utils.date_utils import parse_date
from app.utils.number_utils import parse_number, parse_percentage
from app.utils.type_detection import PhysicalType, SemanticType
from app.utils.validation_utils import is_null_like, parse_boolean


@dataclass(slots=True)
class CleaningStats:
    column_name: str
    physical_type: PhysicalType
    semantic_type: SemanticType
    rows_total: int = 0
    rows_normalized: int = 0
    rows_converted: int = 0
    rows_null_normalized: int = 0
    rows_arabic_repaired: int = 0
    rows_failed_conversion: int = 0
    failed_samples: list[str] = field(default_factory=list)


def clean_column(
    name: str,
    values: list[object],
    *,
    physical_type: PhysicalType,
    semantic_type: SemanticType,
) -> tuple[list[Any], CleaningStats]:
    stats = CleaningStats(name, physical_type, semantic_type, rows_total=len(values))
    out: list[Any] = []

    for raw in values:
        if raw is None:
            out.append(None)
            continue

        s = str(raw)

        # Repair broken Arabic before further processing
        repaired = try_fix_broken_arabic(s)
        if repaired != s:
            stats.rows_arabic_repaired += 1
            s = repaired

        # Normalize text (Arabic + whitespace)
        normalized = normalize_text(s)
        if normalized != s.strip():
            stats.rows_normalized += 1

        if is_null_like(normalized):
            out.append(None)
            stats.rows_null_normalized += 1
            continue

        converted, ok = _convert(normalized, physical_type, semantic_type)
        if ok:
            stats.rows_converted += 1
            out.append(converted)
        else:
            stats.rows_failed_conversion += 1
            if len(stats.failed_samples) < 5:
                stats.failed_samples.append(normalized[:200])
            out.append(None)  # store NULL on failure; raw stays in Bronze

    return out, stats


def _convert(
    value: str,
    physical_type: PhysicalType,
    semantic_type: SemanticType,
) -> tuple[Any, bool]:
    if physical_type in ("integer", "float", "decimal") or semantic_type in ("amount", "quantity"):
        n = parse_number(value)
        if n is None:
            return None, False
        if physical_type == "integer":
            try:
                return int(n), True
            except (ValueError, OverflowError):
                return None, False
        return float(n) if physical_type == "float" else n, True

    if semantic_type == "percentage" or physical_type == "decimal":
        p = parse_percentage(value) if semantic_type == "percentage" else parse_number(value)
        return (float(p), True) if p is not None else (None, False)

    if physical_type in ("date", "datetime") or semantic_type in ("date", "datetime"):
        d = parse_date(value)
        return (d, True) if d is not None else (None, False)

    if physical_type == "boolean" or semantic_type == "boolean":
        b = parse_boolean(value)
        return (b, True) if b is not None else (None, False)

    # Fallback: keep string but length-capped
    return value, True
