"""Profiler: produces table-level and column-level statistics + semantic types.

The profiler works directly on a ``polars.DataFrame`` (typically just-loaded
from Bronze) and writes results into ``dw_metadata.table_profiles`` /
``dw_metadata.column_profiles``.

For very wide / very tall tables, columns are profiled in a streaming way
and sample-based statistics use ``PROFILER_SAMPLE_ROWS`` from settings.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from dataclasses import dataclass, field
from typing import Sequence

import polars as pl
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models import ColumnProfile, TableProfile
from app.utils.arabic_text_normalization import (
    arabic_char_ratio,
    english_char_ratio,
)
from app.utils.date_utils import looks_like_date
from app.utils.number_utils import looks_like_number, looks_like_percentage, parse_number
from app.utils.type_detection import TypeProfile, profile_type
from app.utils.validation_utils import is_null_like

_log = get_logger(__name__)

_CURRENCY_HINT_CHARS = {"$", "€", "£", "¥", "ر", "د", "S", "U", "A"}


# ---------------------------------------------------------------------------
@dataclass(slots=True)
class ColumnProfileResult:
    column_name: str
    original_name: str | None
    type_profile: TypeProfile
    null_count: int
    null_percentage: float
    empty_string_count: int
    unique_count: int
    uniqueness_ratio: float
    min_value: str | None
    max_value: str | None
    mean_value: float | None
    median_value: float | None
    stddev_value: float | None
    top_values: list[tuple[str, int]]
    sample_values: list[str]
    invalid_value_count: int
    arabic_text_percentage: float
    english_text_percentage: float
    numeric_text_percentage: float
    date_text_percentage: float
    percentage_text_percentage: float
    currency_text_percentage: float


@dataclass(slots=True)
class TableProfileResult:
    table_name: str
    layer: str
    row_count: int
    column_count: int
    duplicate_row_count: int
    empty_row_count: int
    memory_bytes: int | None
    candidate_primary_keys: list[str]
    classification: str        # 'fact' | 'dim' | 'flat' | 'bridge'
    columns: list[ColumnProfileResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
class ProfilerService:
    """Build :class:`TableProfileResult` objects and persist them."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.sample_rows = settings.profiler_sample_rows

    # ------------------------------------------------------------------
    def profile_table(
        self,
        *,
        batch_id: str,
        layer: str,
        table_name: str,
        frame: pl.DataFrame,
        original_column_names: Sequence[str] | None = None,
        persist: bool = True,
    ) -> TableProfileResult:
        rows, cols = frame.shape
        sample = frame if rows <= self.sample_rows else frame.sample(self.sample_rows, seed=42)

        empty_row_count = int(
            sample.with_columns(
                pl.all_horizontal([pl.col(c).is_null() | (pl.col(c).cast(pl.Utf8) == "") for c in sample.columns])
                .alias("_is_empty")
            )["_is_empty"].sum()
        )
        # Duplicate rows
        try:
            dup_count = rows - frame.n_unique()
        except Exception:
            dup_count = 0

        col_results: list[ColumnProfileResult] = []
        col_originals = list(original_column_names) if original_column_names else list(frame.columns)

        for safe_name, original in zip(frame.columns, col_originals):
            col_results.append(self._profile_column(safe_name, original, sample[safe_name].to_list()))

        candidate_pks = [
            c.column_name for c in col_results
            if c.uniqueness_ratio >= 0.99 and c.null_percentage < 1.0
        ]

        classification = self._classify_table(col_results, row_count=rows)

        result = TableProfileResult(
            table_name=table_name,
            layer=layer,
            row_count=rows,
            column_count=cols,
            duplicate_row_count=max(0, dup_count),
            empty_row_count=empty_row_count,
            memory_bytes=int(frame.estimated_size()),
            candidate_primary_keys=candidate_pks,
            classification=classification,
            columns=col_results,
        )
        if persist:
            self._persist(batch_id, result)
        return result

    # ------------------------------------------------------------------
    def _profile_column(
        self, name: str, original: str | None, values: list[object]
    ) -> ColumnProfileResult:
        total = len(values)
        nulls = [v for v in values if v is None or is_null_like(v)]
        non_nulls = [v for v in values if v not in nulls]
        non_null_str = [str(v) for v in non_nulls]
        empty_str = sum(1 for v in values if isinstance(v, str) and v.strip() == "")

        uniq = set(non_null_str)
        type_p = profile_type(
            name,
            non_nulls,
            uniqueness_ratio=(len(uniq) / total) if total else 0,
        )

        # Stats for numeric columns
        numeric_vals: list[float] = []
        for v in non_nulls:
            num = parse_number(v)
            if num is not None:
                numeric_vals.append(float(num))
        mean = stdev = median = None
        if numeric_vals:
            mean = sum(numeric_vals) / len(numeric_vals)
            try:
                median = statistics.median(numeric_vals)
            except statistics.StatisticsError:
                median = None
            try:
                stdev = statistics.pstdev(numeric_vals) if len(numeric_vals) > 1 else 0.0
            except statistics.StatisticsError:
                stdev = None

        # Top + sample
        counter = Counter(non_null_str)
        top_values = counter.most_common(10)
        sample_values = [v for v, _ in counter.most_common(5)]

        # Character / format distributions
        ar_pct = (sum(arabic_char_ratio(s) for s in non_null_str) / max(1, len(non_null_str))) * 100
        en_pct = (sum(english_char_ratio(s) for s in non_null_str) / max(1, len(non_null_str))) * 100

        def share(pred) -> float:
            if not non_null_str:
                return 0.0
            return (sum(1 for s in non_null_str if pred(s)) / len(non_null_str)) * 100

        return ColumnProfileResult(
            column_name=name,
            original_name=original,
            type_profile=type_p,
            null_count=len(nulls),
            null_percentage=(len(nulls) / total * 100) if total else 0.0,
            empty_string_count=empty_str,
            unique_count=len(uniq),
            uniqueness_ratio=(len(uniq) / total) if total else 0.0,
            min_value=(min(non_null_str) if non_null_str else None),
            max_value=(max(non_null_str) if non_null_str else None),
            mean_value=mean,
            median_value=median,
            stddev_value=stdev,
            top_values=top_values,
            sample_values=sample_values,
            invalid_value_count=int(
                sum(1 for s in non_null_str if type_p.physical_type in ("integer", "float", "decimal")
                    and not looks_like_number(s))
            ),
            arabic_text_percentage=ar_pct,
            english_text_percentage=en_pct,
            numeric_text_percentage=share(looks_like_number),
            date_text_percentage=share(looks_like_date),
            percentage_text_percentage=share(looks_like_percentage),
            currency_text_percentage=share(lambda s: any(ch in _CURRENCY_HINT_CHARS for ch in s[:6])),
        )

    # ------------------------------------------------------------------
    def _classify_table(self, cols: Sequence[ColumnProfileResult], row_count: int) -> str:
        n_numeric = sum(1 for c in cols if c.type_profile.semantic_type in ("amount", "quantity", "percentage"))
        n_dates = sum(1 for c in cols if c.type_profile.semantic_type in ("date", "datetime"))
        n_ids = sum(1 for c in cols if c.type_profile.semantic_type == "id")
        has_pk = any(c.uniqueness_ratio >= 0.99 for c in cols)

        if n_numeric >= 1 and n_dates >= 1 and n_ids >= 2 and row_count > 100:
            return "fact"
        if has_pk and row_count <= 50_000 and n_numeric == 0:
            return "dim"
        if n_ids >= 2 and n_numeric == 0 and n_dates == 0:
            return "bridge"
        return "flat"

    # ------------------------------------------------------------------
    def _persist(self, batch_id: str, result: TableProfileResult) -> None:
        self.session.add(
            TableProfile(
                batch_id=batch_id,
                layer=result.layer,
                table_name=result.table_name,
                row_count=result.row_count,
                column_count=result.column_count,
                duplicate_row_count=result.duplicate_row_count,
                empty_row_count=result.empty_row_count,
                memory_bytes=result.memory_bytes,
                candidate_primary_keys=json.dumps(result.candidate_primary_keys, ensure_ascii=False),
                classification=result.classification,
            )
        )
        for c in result.columns:
            self.session.add(
                ColumnProfile(
                    batch_id=batch_id,
                    layer=result.layer,
                    table_name=result.table_name,
                    column_name=c.column_name,
                    original_column_name=c.original_name,
                    physical_type=c.type_profile.physical_type,
                    semantic_type=c.type_profile.semantic_type,
                    type_confidence=c.type_profile.confidence,
                    null_count=c.null_count,
                    null_percentage=c.null_percentage,
                    empty_string_count=c.empty_string_count,
                    unique_count=c.unique_count,
                    uniqueness_ratio=c.uniqueness_ratio,
                    min_value=(c.min_value or "")[:512],
                    max_value=(c.max_value or "")[:512],
                    mean_value=c.mean_value,
                    median_value=c.median_value,
                    stddev_value=c.stddev_value,
                    top_values_json=json.dumps(c.top_values, ensure_ascii=False),
                    sample_values_json=json.dumps(c.sample_values, ensure_ascii=False),
                    invalid_value_count=c.invalid_value_count,
                    arabic_text_percentage=c.arabic_text_percentage,
                    english_text_percentage=c.english_text_percentage,
                    numeric_text_percentage=c.numeric_text_percentage,
                    date_text_percentage=c.date_text_percentage,
                    percentage_text_percentage=c.percentage_text_percentage,
                    currency_text_percentage=c.currency_text_percentage,
                )
            )
        self.session.commit()
