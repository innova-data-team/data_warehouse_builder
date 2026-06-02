"""Date / datetime parsing with multi-format and Arabic month support."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Final

from dateutil import parser as _dateutil_parser

from .arabic_text_normalization import normalize_text

# Arabic month names → numeric month
_ARABIC_MONTHS: Final[dict[str, int]] = {
    "يناير": 1, "كانون الثاني": 1,
    "فبراير": 2, "شباط": 2,
    "مارس": 3, "اذار": 3, "آذار": 3,
    "ابريل": 4, "أبريل": 4, "نيسان": 4,
    "مايو": 5, "ايار": 5, "أيار": 5,
    "يونيو": 6, "حزيران": 6,
    "يوليو": 7, "تموز": 7,
    "اغسطس": 8, "أغسطس": 8, "اب": 8, "آب": 8,
    "سبتمبر": 9, "ايلول": 9, "أيلول": 9,
    "اكتوبر": 10, "أكتوبر": 10, "تشرين الاول": 10, "تشرين الأول": 10,
    "نوفمبر": 11, "تشرين الثاني": 11,
    "ديسمبر": 12, "كانون الاول": 12, "كانون الأول": 12,
}

_DATE_HINT_RE: Final = re.compile(
    r"^\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4}(?:[ T]\d{1,2}:\d{1,2}(:\d{1,2})?)?$"
)


def _try_arabic_month(value: str) -> date | None:
    norm = normalize_text(value).lower()
    for month_name, month_num in _ARABIC_MONTHS.items():
        if month_name in norm:
            # extract a 4-digit year and 1-2 digit day
            year_m = re.search(r"\b(19|20)\d{2}\b", norm)
            day_m = re.search(r"\b([1-9]|[12]\d|3[01])\b", norm)
            if year_m and day_m:
                try:
                    return date(int(year_m.group()), month_num, int(day_m.group()))
                except ValueError:
                    return None
    return None


def looks_like_date(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, (date, datetime)):
        return True
    s = normalize_text(str(value))
    if _DATE_HINT_RE.match(s):
        return True
    return _try_arabic_month(s) is not None


def parse_date(value: object, *, dayfirst: bool | None = None) -> datetime | None:
    """Robust date parser. Returns ``None`` if value cannot be parsed.

    ``dayfirst`` defaults to ``True`` because Arabic/European data is usually
    DMY. Set to ``False`` for US-style MDY data.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)

    s = normalize_text(str(value)).strip()
    if not s:
        return None

    ar = _try_arabic_month(s)
    if ar is not None:
        return datetime(ar.year, ar.month, ar.day)

    try:
        return _dateutil_parser.parse(
            s,
            dayfirst=True if dayfirst is None else dayfirst,
            fuzzy=False,
        )
    except (ValueError, OverflowError):
        return None
