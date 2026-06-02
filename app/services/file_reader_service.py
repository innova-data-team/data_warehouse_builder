"""Robust multi-format file reader.

Supports:

* CSV  — auto-detect encoding (chardet + heuristics) and delimiter
         (``,;\\t|``), tolerant of broken rows.
* Excel — ``.xlsx`` / ``.xlsm`` / ``.xls`` via openpyxl; multi-sheet,
          Arabic sheet names, automatic header-row detection when the
          first row is empty or junk.
* JSON  — array of objects, single object, or JSON Lines. Nested
          structures are flattened (path-preserving keys).

All readers return a uniform :class:`ReadResult` containing:

* ``frames`` — a list of ``(logical_name, polars.DataFrame)`` pairs
  (multi-sheet Excel produces one per sheet).
* ``metadata`` — encoding, delimiter, sheet info, etc.

Polars is used as the primary engine; pandas is only used for the Excel
header-detection step because openpyxl cells map naturally to pandas.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import chardet
import polars as pl

from app.core.exceptions import FileFormatError
from app.core.logging import get_logger
from app.utils.column_utils import is_valid_header_row, normalize_headers
from app.utils.file_utils import detect_file_format
from app.utils.json_utils import flatten_json, is_jsonl

_log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class FrameInfo:
    """One logical dataset extracted from a file (often one Excel sheet)."""

    name: str
    frame: pl.DataFrame
    original_columns: list[str]
    sheet_name: str | None = None


@dataclass(slots=True)
class ReadResult:
    file_type: str
    frames: list[FrameInfo]
    detected_encoding: str | None = None
    detected_delimiter: str | None = None
    sheet_count: int | None = None
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def read_file(path: str | Path) -> ReadResult:
    """Dispatch to the appropriate reader based on extension."""
    path = Path(path)
    if not path.exists():
        raise FileFormatError(f"File not found: {path}")

    fmt = detect_file_format(path.name)
    _log.info("Reading file=%s detected_format=%s", path, fmt)

    if fmt == "csv":
        return _read_csv(path)
    if fmt == "excel":
        return _read_excel(path)
    if fmt == "json":
        return _read_json(path)
    raise FileFormatError(
        f"Unsupported file format for '{path.name}'. Allowed: CSV, Excel, JSON."
    )


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
_CSV_CANDIDATE_ENCODINGS: tuple[str, ...] = (
    "utf-8-sig", "utf-8", "cp1256", "windows-1256", "iso-8859-1", "latin-1",
)
_CSV_CANDIDATE_DELIMS: tuple[str, ...] = (",", ";", "\t", "|")


def _detect_encoding(sample: bytes) -> str:
    # 1) BOM-based fast path
    if sample.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    # 2) chardet
    guess = chardet.detect(sample) or {}
    enc = (guess.get("encoding") or "").lower()
    if enc and guess.get("confidence", 0) >= 0.65:
        return enc
    # 3) try each candidate and keep the first that decodes cleanly
    for enc in _CSV_CANDIDATE_ENCODINGS:
        try:
            sample.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "utf-8"


def _detect_delimiter(text_sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(text_sample, delimiters="".join(_CSV_CANDIDATE_DELIMS))
        return dialect.delimiter
    except csv.Error:
        # Fallback: count per-line occurrences and pick the most consistent
        counts = {d: text_sample.count(d) for d in _CSV_CANDIDATE_DELIMS}
        return max(counts.items(), key=lambda kv: kv[1])[0] if any(counts.values()) else ","


def _read_csv(path: Path) -> ReadResult:
    raw = path.read_bytes()
    encoding = _detect_encoding(raw[: 128 * 1024])
    text_sample = raw[: 128 * 1024].decode(encoding, errors="replace")
    delimiter = _detect_delimiter(text_sample)

    _log.debug("CSV: encoding=%s delimiter=%r path=%s", encoding, delimiter, path)

    # Polars is fast and tolerant; fall back to pandas-style if needed.
    try:
        frame = pl.read_csv(
            io.BytesIO(raw),
            encoding=encoding if encoding != "cp1256" else "windows-1256",
            separator=delimiter,
            ignore_errors=True,
            try_parse_dates=False,
            infer_schema_length=0,         # treat everything as strings in Bronze
            has_header=True,
            null_values=["", "NA", "N/A", "null", "NULL", "None"],
        )
    except Exception as exc:  # noqa: BLE001
        raise FileFormatError(f"Failed to read CSV {path.name}: {exc}") from exc

    originals = list(frame.columns)
    renames = normalize_headers(originals)
    frame = frame.rename({orig: r.safe_name for orig, r in zip(originals, renames)})

    return ReadResult(
        file_type="csv",
        frames=[FrameInfo(name=path.stem, frame=frame, original_columns=originals)],
        detected_encoding=encoding,
        detected_delimiter=delimiter,
        sheet_count=1,
    )


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------
def _detect_header_row(rows: list[list[Any]], max_scan: int = 10) -> int:
    """Return the index of the row that looks like a header. Defaults to 0."""
    for idx, row in enumerate(rows[:max_scan]):
        if is_valid_header_row(row):
            return idx
    return 0


def _read_excel(path: Path) -> ReadResult:
    try:
        # openpyxl is needed for header-row detection; we still build polars frames.
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover
        raise FileFormatError("openpyxl is required to read Excel files") from exc

    wb = load_workbook(filename=path, read_only=True, data_only=True)
    frames: list[FrameInfo] = []
    warnings: list[str] = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        if not rows:
            warnings.append(f"Sheet '{sheet_name}' is empty; skipped.")
            continue

        header_idx = _detect_header_row(rows)
        header = [str(c) if c is not None else "" for c in rows[header_idx]]
        body = rows[header_idx + 1 :]

        renames = normalize_headers(header)
        safe_cols = [r.safe_name for r in renames]

        # Pad / truncate body rows to match header length
        data: dict[str, list[Any]] = {c: [] for c in safe_cols}
        for r in body:
            if r is None or all(c is None for c in r):
                continue
            padded = list(r) + [None] * (len(safe_cols) - len(r))
            for col, value in zip(safe_cols, padded[: len(safe_cols)]):
                data[col].append(value)

        if not any(data.values()):
            warnings.append(f"Sheet '{sheet_name}' had no data rows; skipped.")
            continue

        frame = pl.DataFrame({c: [None if v is None else str(v) for v in vs] for c, vs in data.items()})
        frames.append(
            FrameInfo(
                name=f"{path.stem}__{sheet_name}",
                frame=frame,
                original_columns=header,
                sheet_name=sheet_name,
            )
        )

    if not frames:
        raise FileFormatError(f"Excel file {path.name} produced no usable sheets.")

    return ReadResult(
        file_type="excel",
        frames=frames,
        sheet_count=len(wb.sheetnames),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------
def _read_json(path: Path) -> ReadResult:
    text = path.read_text(encoding="utf-8")
    text = text.lstrip("\ufeff")
    records: list[dict[str, Any]] = []

    if is_jsonl(text):
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise FileFormatError(f"Invalid JSONL line in {path.name}: {exc}") from exc
    else:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise FileFormatError(f"Invalid JSON in {path.name}: {exc}") from exc

        if isinstance(parsed, list):
            records = [r if isinstance(r, dict) else {"value": r} for r in parsed]
        elif isinstance(parsed, dict):
            records = [parsed]
        else:
            records = [{"value": parsed}]

    if not records:
        raise FileFormatError(f"JSON file {path.name} contained no records.")

    flattened = [flatten_json(r) for r in records]
    all_keys: list[str] = []
    seen: set[str] = set()
    for rec in flattened:
        for k in rec.keys():
            if k not in seen:
                seen.add(k)
                all_keys.append(k)

    originals = all_keys
    renames = normalize_headers(originals)
    safe_cols = [r.safe_name for r in renames]

    data: dict[str, list[Any]] = {c: [] for c in safe_cols}
    for rec in flattened:
        for orig, safe in zip(originals, safe_cols):
            v = rec.get(orig)
            data[safe].append(None if v is None else str(v))

    frame = pl.DataFrame(data)
    return ReadResult(
        file_type="json",
        frames=[FrameInfo(name=path.stem, frame=frame, original_columns=originals)],
        sheet_count=1,
    )
