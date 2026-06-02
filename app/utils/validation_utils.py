"""Domain-agnostic validation helpers: null tokens and boolean parsing."""

from __future__ import annotations

from typing import Final

from .arabic_text_normalization import normalize_text

NULL_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "",
        "null", "none", "n/a", "na", "n.a", "-", "--",
        "غير متوفر", "لا يوجد", "غير محدد", "غ.م", "غ م",
        "nan", "nat", "missing", "?",
    }
)

_TRUE_TOKENS: Final[frozenset[str]] = frozenset(
    {"true", "t", "yes", "y", "1", "نعم", "ايجابي", "إيجابي", "صح", "صحيح"}
)
_FALSE_TOKENS: Final[frozenset[str]] = frozenset(
    {"false", "f", "no", "n", "0", "لا", "سلبي", "خاطئ", "غير صحيح"}
)


def is_null_like(value: object) -> bool:
    if value is None:
        return True
    s = normalize_text(str(value)).strip().lower()
    return s in NULL_TOKENS


def parse_boolean(value: object) -> bool | None:
    """Return ``True`` / ``False`` if the value is a recognized boolean,
    otherwise ``None``.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    s = normalize_text(str(value)).strip().lower()
    if s in _TRUE_TOKENS:
        return True
    if s in _FALSE_TOKENS:
        return False
    return None
