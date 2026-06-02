"""Column-name helpers: deduplication, original→safe mapping, header detection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from unidecode import unidecode

from .arabic_text_normalization import is_arabic_text, normalize_text
from .sql_utils import safe_column_name

_NON_WORD_RE = re.compile(r"[^\w\s]+", flags=re.UNICODE)


@dataclass(slots=True)
class ColumnRename:
    """Mapping between an original column name and its safe technical name."""

    original_name: str
    normalized_name: str   # NFKC + Arabic-normalized but still human-readable
    safe_name: str         # MySQL-safe snake_case ASCII
    is_arabic: bool
    is_empty: bool


def normalize_headers(originals: Iterable[str | None]) -> list[ColumnRename]:
    """Normalize a sequence of raw header strings.

    * Empty / None / whitespace-only names become ``col_unnamed_N``.
    * Duplicates get a stable ``__2``, ``__3`` suffix.
    * Arabic names are NFKC-normalized for display; the safe technical
      name uses :func:`unidecode` (transliteration) so MySQL identifiers
      are pure ASCII snake_case.
    """
    raw = list(originals)
    seen_safe: dict[str, int] = {}
    out: list[ColumnRename] = []

    for idx, name in enumerate(raw):
        original = "" if name is None else str(name)
        is_empty = original.strip() == ""
        display = "" if is_empty else normalize_text(original, for_identifier=True)

        if is_empty:
            safe_seed = f"col_unnamed_{idx + 1}"
            is_arabic = False
        else:
            is_arabic = is_arabic_text(display)
            # Transliterate Arabic so the ASCII name is meaningful.
            ascii_seed = unidecode(display) if is_arabic else display
            ascii_seed = _NON_WORD_RE.sub(" ", ascii_seed).strip()
            safe_seed = safe_column_name(ascii_seed) if ascii_seed else f"col_{idx + 1}"

        # Deduplicate
        safe = safe_seed
        if safe in seen_safe:
            seen_safe[safe] += 1
            safe = f"{safe_seed}__{seen_safe[safe_seed]}"
        else:
            seen_safe[safe] = 1

        out.append(
            ColumnRename(
                original_name=original,
                normalized_name=display,
                safe_name=safe,
                is_arabic=is_arabic,
                is_empty=is_empty,
            )
        )

    return out


def is_valid_header_row(values: Iterable[object]) -> bool:
    """Heuristic: a header row should be mostly non-null short text."""
    vals = list(values)
    if not vals:
        return False
    nonnull = [v for v in vals if v is not None and str(v).strip()]
    if len(nonnull) < max(1, len(vals) // 2):
        return False
    # Headers shouldn't look like pure numbers
    numeric = sum(1 for v in nonnull if str(v).replace(".", "", 1).lstrip("-").isdigit())
    return numeric / max(1, len(nonnull)) < 0.5
