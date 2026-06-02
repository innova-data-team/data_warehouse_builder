"""Detect physical types (numeric, date, boolean…) and semantic types.

Both detectors are sample-based. ``detect_physical_type`` returns the most
likely SQL-storage-relevant type, while ``detect_semantic_type`` returns a
business-meaning label (``id``, ``email``, ``amount`` …).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Literal

from .arabic_text_normalization import normalize_text
from .date_utils import looks_like_date
from .number_utils import looks_like_number, looks_like_percentage
from .validation_utils import NULL_TOKENS, parse_boolean

PhysicalType = Literal[
    "integer", "float", "decimal", "boolean", "date", "datetime",
    "string", "text", "unknown",
]

SemanticType = Literal[
    "id", "name", "description", "date", "datetime", "amount", "quantity",
    "percentage", "category", "status", "email", "phone", "national_id",
    "code", "boolean", "url", "address", "unknown",
]


# ---------------------------------------------------------------------------
# Pattern detectors
# ---------------------------------------------------------------------------
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
# Saudi mobile and generic intl phone
_PHONE_RE = re.compile(r"^\+?\d[\d\s\-()]{6,18}\d$")
# Saudi national id (10 digits) or generic 9–12 digit national id
_NATID_RE = re.compile(r"^\d{9,12}$")
_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-/]{1,30}$")
_INT_RE = re.compile(r"^-?\d+$")


@dataclass(slots=True)
class TypeProfile:
    physical_type: PhysicalType
    semantic_type: SemanticType
    type_distribution: dict[str, float]  # share of values per detected type
    confidence: float                     # 0-1, share of values matching physical_type


# ---------------------------------------------------------------------------
# Physical-type detection
# ---------------------------------------------------------------------------
def detect_physical_type(values: Iterable[object]) -> tuple[PhysicalType, dict[str, float], float]:
    """Classify a column's physical type from its values."""
    samples = [v for v in values if v is not None]
    if not samples:
        return "unknown", {}, 0.0

    counts: Counter[str] = Counter()
    for v in samples:
        s = str(v).strip()
        if not s or s.lower() in NULL_TOKENS:
            counts["null"] += 1
        elif parse_boolean(s) is not None:
            counts["boolean"] += 1
        elif _INT_RE.match(s):
            counts["integer"] += 1
        elif looks_like_percentage(s):
            counts["float"] += 1   # percentages become floats in Silver
        elif looks_like_number(s):
            counts["float"] += 1
        elif looks_like_date(s):
            counts["date"] += 1
        else:
            counts["string"] += 1

    total = sum(counts.values())
    distribution = {k: c / total for k, c in counts.items()}
    # Exclude pure null from the winner calculation
    non_null = {k: c for k, c in counts.items() if k != "null"}
    if not non_null:
        return "unknown", distribution, 0.0

    winner, winner_count = max(non_null.items(), key=lambda kv: kv[1])
    non_null_total = sum(non_null.values())
    confidence = winner_count / non_null_total if non_null_total else 0.0

    # Promote integer/float → decimal when sample contains both
    physical: PhysicalType
    if winner == "integer" and "float" in non_null:
        physical = "decimal"
    elif winner in ("integer", "float", "boolean", "date", "string"):
        physical = winner  # type: ignore[assignment]
    else:
        physical = "string"

    # Long strings get bumped to TEXT
    if physical == "string":
        if any(len(str(v)) > 255 for v in samples):
            physical = "text"

    return physical, distribution, confidence


# ---------------------------------------------------------------------------
# Semantic-type detection
# ---------------------------------------------------------------------------
def detect_semantic_type(
    column_name: str,
    values: Iterable[object],
    *,
    uniqueness_ratio: float | None = None,
) -> SemanticType:
    """Infer the business meaning of a column from its name and values."""
    name_norm = normalize_text(column_name, for_identifier=True).lower()
    samples_str = [str(v).strip() for v in values if v is not None and str(v).strip()]
    if not samples_str:
        return "unknown"

    # Name-based fast paths
    name_hits: list[tuple[SemanticType, list[str]]] = [
        ("email",       ["email", "e-mail", "بريد"]),
        ("phone",       ["phone", "mobile", "tel", "هاتف", "جوال", "موبايل"]),
        ("national_id", ["national_id", "nid", "iqama", "رقم الهوية", "الهوية"]),
        ("url",         ["url", "link", "website", "موقع", "رابط"]),
        ("address",     ["address", "city", "country", "region", "عنوان", "مدينة", "دولة", "منطقة"]),
        ("date",        ["date", "تاريخ"]),
        ("datetime",    ["timestamp", "datetime", "وقت"]),
        ("amount",      ["amount", "price", "cost", "revenue", "total", "salary",
                         "سعر", "تكلفة", "إيراد", "ايراد", "راتب", "إجمالي", "اجمالي"]),
        ("quantity",    ["qty", "quantity", "count", "عدد", "كمية"]),
        ("percentage",  ["pct", "percent", "rate", "نسبة"]),
        ("status",      ["status", "state", "حالة"]),
        ("category",    ["category", "type", "class", "نوع", "فئة", "صنف"]),
        ("code",        ["code", "كود", "رمز"]),
        ("id",          ["_id", "id_", "id", "رقم", "معرف"]),
        ("name",        ["name", "title", "اسم", "عنوان"]),
        ("description", ["description", "notes", "comment", "وصف", "ملاحظ"]),
    ]
    for sem, keywords in name_hits:
        if any(k in name_norm for k in keywords):
            # Sanity-check ID using uniqueness ratio when available
            if sem == "id" and uniqueness_ratio is not None and uniqueness_ratio < 0.9:
                continue
            return sem

    # Value-based fallbacks
    sample = samples_str[:200]

    def share(pred) -> float:
        return sum(1 for v in sample if pred(v)) / len(sample)

    if share(lambda v: bool(_EMAIL_RE.match(v))) >= 0.8:
        return "email"
    if share(lambda v: bool(_URL_RE.match(v))) >= 0.8:
        return "url"
    if share(lambda v: bool(_PHONE_RE.match(v))) >= 0.8:
        return "phone"
    if share(lambda v: bool(_NATID_RE.match(v))) >= 0.8:
        return "national_id"
    if share(lambda v: looks_like_percentage(v)) >= 0.7:
        return "percentage"
    if share(lambda v: looks_like_number(v)) >= 0.9:
        return "amount" if uniqueness_ratio and uniqueness_ratio < 0.95 else "quantity"
    if share(looks_like_date) >= 0.8:
        return "date"
    if share(lambda v: parse_boolean(v) is not None) >= 0.9:
        return "boolean"
    if uniqueness_ratio is not None and uniqueness_ratio < 0.1:
        return "category"

    return "unknown"


def profile_type(
    column_name: str,
    values: Iterable[object],
    *,
    uniqueness_ratio: float | None = None,
) -> TypeProfile:
    """Convenience wrapper returning a complete :class:`TypeProfile`."""
    values_list = list(values)
    physical, dist, conf = detect_physical_type(values_list)
    semantic = detect_semantic_type(
        column_name, values_list, uniqueness_ratio=uniqueness_ratio
    )
    return TypeProfile(physical, semantic, dist, conf)
