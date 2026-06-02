"""Number / percentage / currency parsing utilities.

These functions are robust to:

* Arabic-Indic and Persian digits (already converted upstream by
  :mod:`arabic_text_normalization`, but handled here as well for safety).
* Thousand separators: ``,`` (en), ``٬`` (ar), spaces, apostrophes.
* Decimal separators: ``.`` (en) or ``٫`` (ar).
* Trailing currency symbols: ``$``, ``€``, ``ر.س``, ``SAR``, ``USD``…
* Percent signs: ``%``, ``٪``.
* Parentheses for negatives: ``(123.45)`` → ``-123.45``.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Final

from .arabic_text_normalization import normalize_text

# Currency tokens we strip when parsing numbers
_CURRENCY_TOKENS_RE: Final = re.compile(
    r"(?:USD|EUR|SAR|AED|EGP|JOD|KWD|QAR|BHD|OMR|ر\.س|ر\.ع|د\.ك|ج\.م|د\.أ|د\.ك|\$|€|£|¥)",
    flags=re.IGNORECASE,
)
_NEG_PAREN_RE: Final = re.compile(r"^\s*\((.+?)\)\s*$")
_PCT_RE: Final = re.compile(r"%$")
_NUMBER_RE: Final = re.compile(r"^-?\d+(\.\d+)?$")


def _strip_to_number(value: str) -> str:
    s = normalize_text(value).strip()
    s = _CURRENCY_TOKENS_RE.sub("", s).strip()
    # Negative in parens
    m = _NEG_PAREN_RE.match(s)
    if m:
        s = "-" + m.group(1)
    # Remove thousand separators
    s = s.replace(" ", "").replace("'", "")
    # Heuristic: if both ',' and '.' appear, comma is thousands; else assume
    # comma is decimal only if there is exactly one comma and no dot
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s and "." not in s:
        # Treat as decimal separator only when fractional length looks decimal
        # e.g. "12,5" -> "12.5"; "1,234" -> "1234"
        whole, _, frac = s.partition(",")
        if len(frac) <= 2:
            s = f"{whole}.{frac}"
        else:
            s = whole + frac
    return s


def looks_like_number(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, (int, float, Decimal)):
        return True
    s = _strip_to_number(str(value)).replace("%", "")
    return bool(_NUMBER_RE.match(s))


def parse_number(value: object) -> Decimal | None:
    """Return ``Decimal`` or ``None`` if value cannot be parsed."""
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None

    s = _strip_to_number(str(value))
    if s.endswith("%"):
        s = s[:-1]
    if not s or s == "-":
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def looks_like_percentage(value: object) -> bool:
    if value is None:
        return False
    s = normalize_text(str(value)).strip()
    if s.endswith("%"):
        return looks_like_number(s[:-1])
    return False


def parse_percentage(value: object) -> Decimal | None:
    """Parse ``5% / ٥٪ / 0.05`` and return a fraction in ``[0, 1]``.

    * ``"5%"`` → ``0.05``
    * ``"5"``   → ``0.05`` (interpreted as percent if > 1)
    * ``"0.05"`` → ``0.05`` (already a fraction)
    """
    if value is None:
        return None
    s = normalize_text(str(value)).strip()
    explicit_pct = s.endswith("%")
    n = parse_number(s)
    if n is None:
        return None
    if explicit_pct:
        return n / Decimal(100)
    if n > 1:
        return n / Decimal(100)
    return n
