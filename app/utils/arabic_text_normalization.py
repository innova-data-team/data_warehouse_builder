"""Arabic-aware text normalization.

Designed for use on both **column names** (single short strings) and
**cell values** (potentially long strings, possibly mixed Ar/En).

The normalization pipeline is opinionated but configurable through
``app.core.config.Settings``:

    1.  Unicode NFKC
    2.  Strip BOM and zero-width characters
    3.  Optionally remove diacritics (tashkeel)
    4.  Remove tatweel ('ـ')
    5.  Canonicalize letter variants (alef family, alef-maqsura, optional ta-marbuta)
    6.  Convert Arabic-Indic and Persian digits to ASCII
    7.  Normalize Arabic punctuation
    8.  Collapse whitespace and trim

It also exposes a few classification helpers used by the profiler.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

from app.core.config import settings

# ---------------------------------------------------------------------------
# Character maps (kept as module-level constants for performance)
# ---------------------------------------------------------------------------

# Unicode ranges for Arabic script (basic + supplement + extended-A)
_ARABIC_RE: Final = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")
_ENGLISH_RE: Final = re.compile(r"[A-Za-z]")
_DIGIT_RE: Final = re.compile(r"\d")

# Tashkeel / harakat
_TASHKEEL_RE: Final = re.compile(r"[\u064B-\u065F\u0670]")
# Tatweel (kashida)
_TATWEEL: Final = "\u0640"
# Zero-width + BOM
_ZW_RE: Final = re.compile(r"[\u200B-\u200F\u202A-\u202E\u2066-\u2069\uFEFF]")

# Letter normalization (always-on)
_LETTER_MAP_ALWAYS: Final = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ؤ": "و",
        "ئ": "ي",
    }
)

# Optional: ta-marbuta → ha
_LETTER_MAP_TAA: Final = str.maketrans({"ة": "ه"})

# Arabic-Indic digits (٠١٢٣٤٥٦٧٨٩) and Persian variants (۰۱۲...)
_DIGIT_MAP: Final = str.maketrans(
    {
        "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
        "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
        "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
        "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    }
)

# Arabic punctuation → ASCII equivalents
_PUNCT_MAP: Final = str.maketrans(
    {
        "،": ",",
        "؛": ";",
        "؟": "?",
        "٪": "%",
        "٫": ".",   # Arabic decimal separator
        "٬": ",",   # Arabic thousands separator
        "ـ": "",
    }
)

# Mojibake fingerprints commonly produced by mis-decoding cp1256 as latin-1
_MOJIBAKE_HINT_RE: Final = re.compile(r"[ÃÂØÙÚ]{2,}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def normalize_text(value: str | None, *, for_identifier: bool = False) -> str:
    """Normalize an Arabic / mixed Arabic-English string.

    Parameters
    ----------
    value
        The input string. ``None`` and non-string types return ``""``.
    for_identifier
        When ``True``, applies extra conservatism suitable for column
        names (no punctuation tweaks beyond stripping, and never collapse
        ta-marbuta even if globally enabled).
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)

    if not settings.enable_arabic_normalization:
        return value.strip()

    # NFKC unifies presentation forms ("ﻻ" → "لا", full-width digits, etc.)
    s = unicodedata.normalize("NFKC", value)

    s = _ZW_RE.sub("", s)
    if settings.tashkeel_removal:
        s = _TASHKEEL_RE.sub("", s)
    s = s.replace(_TATWEEL, "")

    s = s.translate(_LETTER_MAP_ALWAYS)
    if settings.normalize_taa_marbuta and not for_identifier:
        s = s.translate(_LETTER_MAP_TAA)

    s = s.translate(_DIGIT_MAP)
    if not for_identifier:
        s = s.translate(_PUNCT_MAP)

    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_arabic_text(value: str) -> bool:
    """Return True if the string contains at least one Arabic letter."""
    return bool(_ARABIC_RE.search(value or ""))


def arabic_char_ratio(value: str) -> float:
    """Fraction of non-space characters that are Arabic letters."""
    if not value:
        return 0.0
    letters = [c for c in value if not c.isspace()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if _ARABIC_RE.match(c)) / len(letters)


def english_char_ratio(value: str) -> float:
    """Fraction of non-space characters that are A–Z / a–z."""
    if not value:
        return 0.0
    letters = [c for c in value if not c.isspace()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if _ENGLISH_RE.match(c)) / len(letters)


def looks_like_broken_arabic(value: str) -> bool:
    """Heuristic detector for cp1256-as-latin1 mojibake."""
    if not value:
        return False
    return bool(_MOJIBAKE_HINT_RE.search(value))


def try_fix_broken_arabic(value: str) -> str:
    """Attempt to recover broken Arabic by re-decoding as cp1256.

    If the recovered string contains *more* Arabic letters than the
    original, we keep it. Otherwise we return the input untouched.
    """
    if not value or not looks_like_broken_arabic(value):
        return value
    try:
        recovered = value.encode("latin-1", errors="ignore").decode(
            "cp1256", errors="ignore"
        )
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
    if arabic_char_ratio(recovered) > arabic_char_ratio(value):
        return recovered
    return value
