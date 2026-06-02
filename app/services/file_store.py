"""File-based batch storage (parquet + JSON) — no MySQL required."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from app.core.config import settings
from app.core.logging import get_logger
from app.services.data_quality_service import QualityIssueDraft
from app.services.profiler_service import ColumnProfileResult, TableProfileResult

_log = get_logger(__name__)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)!r} is not JSON serializable")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class StoredFile:
    file_id: str
    batch_id: str
    original_file_name: str
    stored_file_path: str
    file_type: str
    file_size: int
    file_hash: str
    upload_time: str
    status: str = "uploaded"


@dataclass
class StoredBronzeTable:
    id: int
    batch_id: str
    file_id: str
    table_name: str
    source_file_name: str
    source_sheet_name: str | None
    row_count: int
    column_count: int
    failed_row_count: int = 0
    parquet_path: str = ""


@dataclass
class StoredSilverTable:
    id: int
    batch_id: str
    bronze_table_id: int
    table_name: str
    row_count: int
    column_count: int
    dedup_removed_rows: int
    quality_score: float
    parquet_path: str = ""


@dataclass
class StoredGoldTable:
    id: int
    batch_id: str
    table_name: str
    role: str
    row_count: int
    column_count: int
    source_silver_tables: str = ""
    parquet_path: str = ""


@dataclass
class StoredRelationshipSuggestion:
    id: int
    batch_id: str
    source_table: str
    source_column: str
    source_original_column: str | None
    target_table: str
    target_column: str
    target_original_column: str | None
    suggested_relation_type: str
    confidence_score: float
    column_name_similarity_score: float | None = None
    value_overlap_score: float | None = None
    data_type_compatibility_score: float | None = None
    cardinality_score: float | None = None
    matching_values_count: int | None = None
    source_distinct_count: int | None = None
    target_distinct_count: int | None = None
    source_null_percentage: float | None = None
    target_null_percentage: float | None = None
    risk_level: str | None = None
    risk_reason: str | None = None
    recommendation: str | None = None
    status: str = "suggested"


@dataclass
class StoredApprovedRelationship:
    id: int
    batch_id: str
    source_table: str
    source_column: str
    target_table: str
    target_column: str
    relation_type: str
    note: str | None = None
    decided_by: str | None = None
    decided_at: str | None = None


class FileBatchStore:
    """Read/write batch artifacts under ``storage/batches/{batch_id}/``."""

    def __init__(self, batch_id: str) -> None:
        self.batch_id = batch_id
        self.root = settings.batch_data_dir(batch_id)

    def _path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    # ---- batch manifest ------------------------------------------------
    def save_batch(self, *, created_by: str | None = None, stage: str = "uploaded") -> None:
        now = datetime.utcnow().isoformat()
        existing = self.load_batch()
        data = {
            "batch_id": self.batch_id,
            "status": stage,
            "current_stage": stage,
            "created_at": existing.get("created_at", now),
            "updated_at": now,
            "created_by": created_by or existing.get("created_by"),
        }
        _write_json(self._path("batch.json"), data)

    def load_batch(self) -> dict[str, Any]:
        return _read_json(self._path("batch.json"), {})

    def set_stage(self, stage: str) -> None:
        data = self.load_batch()
        data["current_stage"] = stage
        data["status"] = stage
        data["updated_at"] = datetime.utcnow().isoformat()
        _write_json(self._path("batch.json"), data)

    # ---- pipeline progress (finished / pending / running) ---------------
    def load_pipeline_progress(self) -> dict[str, dict]:
        return _read_json(self._path("pipeline_progress.json"), {}).get("steps", {})

    def save_pipeline_step(
        self, step: str, state: str, *, message: str = "", detail: str = "",
    ) -> None:
        data = _read_json(self._path("pipeline_progress.json"), {"steps": {}})
        data["steps"][step] = {
            "state": state,
            "message": message,
            "detail": detail,
            "updated_at": datetime.utcnow().isoformat(),
        }
        _write_json(self._path("pipeline_progress.json"), data)

    def mark_upload_done(self, file_count: int) -> None:
        self.save_pipeline_step(
            "upload", "done",
            message=f"{file_count} file(s) uploaded",
        )

    # ---- uploaded files ------------------------------------------------
    def list_files(self) -> list[StoredFile]:
        rows = _read_json(self._path("files.json"), [])
        return [StoredFile(**r) for r in rows]

    def add_file(self, record: StoredFile) -> None:
        files = self.list_files()
        files.append(record)
        _write_json(self._path("files.json"), [asdict(f) for f in files])

    # ---- bronze --------------------------------------------------------
    def list_bronze_tables(self) -> list[StoredBronzeTable]:
        rows = _read_json(self._path("bronze_tables.json"), [])
        return [StoredBronzeTable(**r) for r in rows]

    def save_bronze_table(self, table: StoredBronzeTable) -> None:
        tables = self.list_bronze_tables()
        tables.append(table)
        _write_json(self._path("bronze_tables.json"), [asdict(t) for t in tables])

    def write_bronze_parquet(self, table_name: str, frame: pl.DataFrame) -> Path:
        out = self._path("bronze", f"{table_name}.parquet")
        out.parent.mkdir(parents=True, exist_ok=True)
        frame.write_parquet(out)
        return out

    def read_bronze_parquet(self, table_name: str) -> pl.DataFrame:
        path = self._path("bronze", f"{table_name}.parquet")
        if not path.exists():
            return pl.DataFrame()
        return pl.read_parquet(path)

    # ---- silver --------------------------------------------------------
    def list_silver_tables(self) -> list[StoredSilverTable]:
        rows = _read_json(self._path("silver_tables.json"), [])
        return [StoredSilverTable(**r) for r in rows]

    def save_silver_table(self, table: StoredSilverTable) -> None:
        tables = self.list_silver_tables()
        tables.append(table)
        _write_json(self._path("silver_tables.json"), [asdict(t) for t in tables])

    def write_silver_parquet(self, table_name: str, frame: pl.DataFrame) -> Path:
        out = self._path("silver", f"{table_name}.parquet")
        out.parent.mkdir(parents=True, exist_ok=True)
        frame.write_parquet(out)
        return out

    def read_silver_parquet(self, table_name: str) -> pl.DataFrame:
        path = self._path("silver", f"{table_name}.parquet")
        if not path.exists():
            return pl.DataFrame()
        return pl.read_parquet(path)

    def read_gold_parquet(self, table_name: str) -> pl.DataFrame:
        path = self._path("gold", f"{table_name}.parquet")
        if not path.exists():
            return pl.DataFrame()
        return pl.read_parquet(path)

    # ---- gold ----------------------------------------------------------
    def list_gold_tables(self) -> list[StoredGoldTable]:
        rows = _read_json(self._path("gold_tables.json"), [])
        return [StoredGoldTable(**r) for r in rows]

    def save_gold_table(self, table: StoredGoldTable) -> None:
        tables = self.list_gold_tables()
        tables.append(table)
        _write_json(self._path("gold_tables.json"), [asdict(t) for t in tables])

    def write_gold_parquet(self, table_name: str, frame: pl.DataFrame) -> Path:
        out = self._path("gold", f"{table_name}.parquet")
        out.parent.mkdir(parents=True, exist_ok=True)
        frame.write_parquet(out)
        return out

    # ---- profiles ------------------------------------------------------
    def save_table_profile(self, profile: TableProfileResult) -> None:
        key = f"{profile.layer}_{profile.table_name}"
        data = {
            "table_name": profile.table_name,
            "layer": profile.layer,
            "row_count": profile.row_count,
            "column_count": profile.column_count,
            "duplicate_row_count": profile.duplicate_row_count,
            "empty_row_count": profile.empty_row_count,
            "memory_bytes": profile.memory_bytes,
            "candidate_primary_keys": profile.candidate_primary_keys,
            "classification": profile.classification,
            "columns": [_column_profile_to_dict(c) for c in profile.columns],
        }
        _write_json(self._path("profiles", f"{key}.json"), data)

    def list_table_profiles(self, layer: str | None = None) -> list[dict[str, Any]]:
        prof_dir = self._path("profiles")
        if not prof_dir.exists():
            return []
        out: list[dict[str, Any]] = []
        for p in sorted(prof_dir.glob("*.json")):
            data = _read_json(p, {})
            if layer and data.get("layer") != layer:
                continue
            out.append(data)
        return out

    def list_column_profiles(self, layer: str | None = None) -> list[dict[str, Any]]:
        cols: list[dict[str, Any]] = []
        for tp in self.list_table_profiles(layer):
            for c in tp.get("columns", []):
                cols.append({
                    "batch_id": self.batch_id,
                    "layer": tp["layer"],
                    "table_name": tp["table_name"],
                    **c,
                })
        return cols

    # ---- quality issues ------------------------------------------------
    def save_quality_issues(self, drafts: list[QualityIssueDraft]) -> None:
        existing = _read_json(self._path("quality_issues.json"), [])
        for d in drafts:
            existing.append({"batch_id": self.batch_id, **asdict(d)})
        _write_json(self._path("quality_issues.json"), existing)

    def list_quality_issues(self) -> list[dict[str, Any]]:
        return _read_json(self._path("quality_issues.json"), [])

    # ---- relationships -------------------------------------------------
    def save_suggestions(self, suggestions: list[StoredRelationshipSuggestion]) -> None:
        _write_json(
            self._path("relationships", "suggestions.json"),
            [asdict(s) for s in suggestions],
        )

    def list_suggestions(self) -> list[StoredRelationshipSuggestion]:
        rows = _read_json(self._path("relationships", "suggestions.json"), [])
        return [StoredRelationshipSuggestion(**r) for r in rows]

    def save_approved(self, approved: list[StoredApprovedRelationship]) -> None:
        _write_json(
            self._path("relationships", "approved.json"),
            [asdict(a) for a in approved],
        )

    def list_approved(self) -> list[StoredApprovedRelationship]:
        rows = _read_json(self._path("relationships", "approved.json"), [])
        return [StoredApprovedRelationship(**r) for r in rows]

    def next_id(self, kind: str) -> int:
        counter_path = self._path("_counters.json")
        counters = _read_json(counter_path, {})
        n = int(counters.get(kind, 0)) + 1
        counters[kind] = n
        _write_json(counter_path, counters)
        return n


def _column_profile_to_dict(c: ColumnProfileResult) -> dict[str, Any]:
    return {
        "column_name": c.column_name,
        "original_column_name": c.original_name,
        "physical_type": c.type_profile.physical_type,
        "semantic_type": c.type_profile.semantic_type,
        "type_confidence": c.type_profile.confidence,
        "null_count": c.null_count,
        "null_percentage": c.null_percentage,
        "empty_string_count": c.empty_string_count,
        "unique_count": c.unique_count,
        "uniqueness_ratio": c.uniqueness_ratio,
        "min_value": c.min_value,
        "max_value": c.max_value,
        "mean_value": c.mean_value,
        "median_value": c.median_value,
        "stddev_value": c.stddev_value,
        "top_values_json": json.dumps(c.top_values, ensure_ascii=False),
        "sample_values_json": json.dumps(c.sample_values, ensure_ascii=False),
        "invalid_value_count": c.invalid_value_count,
        "arabic_text_percentage": c.arabic_text_percentage,
        "english_text_percentage": c.english_text_percentage,
        "numeric_text_percentage": c.numeric_text_percentage,
        "date_text_percentage": c.date_text_percentage,
        "percentage_text_percentage": c.percentage_text_percentage,
        "currency_text_percentage": c.currency_text_percentage,
    }


def list_all_batches() -> list[str]:
    """Return batch IDs sorted by most recently updated."""
    seen: set[str] = set()
    items: list[tuple[float, str]] = []

    batches_dir = settings.storage_root / "batches"
    if batches_dir.exists():
        for d in batches_dir.iterdir():
            if not d.is_dir():
                continue
            manifest = d / "batch.json"
            mtime = manifest.stat().st_mtime if manifest.exists() else d.stat().st_mtime
            items.append((mtime, d.name))
            seen.add(d.name)

    # Include raw-only batches (upload started but manifest not yet visible)
    raw_root = settings.raw_dir
    if raw_root.exists():
        for d in raw_root.iterdir():
            if d.is_dir() and d.name not in seen:
                items.append((d.stat().st_mtime, d.name))
                seen.add(d.name)

    items.sort(reverse=True)
    return [bid for _, bid in items]
