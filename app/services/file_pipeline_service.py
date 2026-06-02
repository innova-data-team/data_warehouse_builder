"""File-based pipeline — upload, bronze, silver, profiles, DQ, relationships, gold."""

from __future__ import annotations

from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Iterable

import polars as pl

from app.core.config import settings
from app.core.exceptions import ApprovalRequiredError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.schemas.pipeline_schema import PipelineStageResult, PipelineStatus
from app.schemas.upload_schema import UploadResponse, UploadedFileInfo
from app.services.cleaner_service import clean_column
from app.services.data_quality_service import DataQualityService
from app.services.file_reader_service import read_file
from app.services.file_store import (
    FileBatchStore,
    StoredApprovedRelationship,
    StoredBronzeTable,
    StoredFile,
    StoredGoldTable,
    StoredRelationshipSuggestion,
    StoredSilverTable,
    list_all_batches,
)
from app.services.profiler_service import ProfilerService
from app.utils.arabic_text_normalization import normalize_text
from app.utils.file_utils import (
    detect_file_format,
    new_batch_id,
    new_file_id,
    safe_filename,
)
from app.utils.hash_utils import hash_file_sha256, hash_record
from app.utils.sql_utils import safe_table_name

_log = get_logger(__name__)

BRONZE_META = (
    "_bronze_id", "_batch_id", "_source_file_id", "_source_file_name",
    "_source_sheet_name", "_source_row_number", "_raw_record_hash", "_ingested_at",
)
_ID_PATTERNS = ("id", "code", "number", "no", "key", "رقم", "كود", "معرف")


class FilePipelineService:
    """Run the warehouse pipeline using parquet + JSON only."""

    def __init__(self) -> None:
        self._profiler = ProfilerService(session=None)  # type: ignore[arg-type]
        self._dq = DataQualityService(session=None)  # type: ignore[arg-type]

    @staticmethod
    def list_batches() -> list[str]:
        return list_all_batches()

    def upload_batch_sync(
        self,
        files: Iterable[tuple[str, bytes]],
        *,
        batch_id: str | None = None,
        created_by: str | None = None,
    ) -> UploadResponse:
        batch_id = batch_id or new_batch_id()
        store = FileBatchStore(batch_id)
        store.save_batch(created_by=created_by, stage="uploaded")
        batch_dir = settings.batch_raw_dir(batch_id)

        infos: list[UploadedFileInfo] = []
        total_bytes = 0
        max_bytes = settings.max_upload_mb * 1024 * 1024

        for filename, content in files:
            if not filename:
                raise ValidationError("Upload missing filename.")
            file_type = detect_file_format(filename)
            if file_type == "unknown":
                raise ValidationError(f"Unsupported file type for '{filename}'.")
            if len(content) > max_bytes:
                raise ValidationError(
                    f"File '{filename}' exceeds MAX_UPLOAD_MB={settings.max_upload_mb}MB."
                )

            safe_name = safe_filename(filename)
            file_id = new_file_id()
            stored_path = batch_dir / f"{file_id}__{safe_name}"
            stored_path.write_bytes(content)
            total_bytes += len(content)
            file_hash = hash_file_sha256(stored_path)

            store.add_file(
                StoredFile(
                    file_id=file_id,
                    batch_id=batch_id,
                    original_file_name=filename,
                    stored_file_path=str(stored_path),
                    file_type=file_type,
                    file_size=len(content),
                    file_hash=file_hash,
                    upload_time=datetime.utcnow().isoformat(),
                )
            )
            infos.append(
                UploadedFileInfo(
                    file_id=file_id,
                    original_file_name=filename,
                    stored_file_path=str(stored_path),
                    file_type=file_type,  # type: ignore[arg-type]
                    file_size=len(content),
                    file_hash=file_hash,
                )
            )

        store.mark_upload_done(len(infos))
        for step in ("bronze", "silver", "relationships", "gold"):
            if step not in store.load_pipeline_progress():
                store.save_pipeline_step(step, "pending", message="Not started")

        return UploadResponse(
            batch_id=batch_id,
            files=infos,
            total_files=len(infos),
            total_bytes=total_bytes,
        )

    def status(self, batch_id: str) -> PipelineStatus:
        self._require_batch(batch_id)
        store = FileBatchStore(batch_id)
        bronze = [t.table_name for t in store.list_bronze_tables()]
        silver = [t.table_name for t in store.list_silver_tables()]
        gold = store.list_gold_tables()
        gold_tables = [t.table_name for t in gold if t.role in ("fact", "dim", "flat")]
        gold_views = [t.table_name for t in gold if t.role == "view"]
        suggestions = store.list_suggestions()
        approved = store.list_approved()
        issues = store.list_quality_issues()

        if gold_tables:
            current = "gold_done"
        elif suggestions:
            current = "awaiting_approval"
        elif silver:
            current = "silver_done"
        elif bronze:
            current = "bronze_done"
        else:
            current = "uploaded"

        return PipelineStatus(
            batch_id=batch_id,
            current_stage=current,  # type: ignore[arg-type]
            stages=[],
            bronze_tables=bronze,
            silver_tables=silver,
            gold_tables=gold_tables,
            gold_views=gold_views,
            suggestion_count=len(suggestions),
            approved_count=len(approved),
            quality_issue_count=len(issues),
        )

    def run_until_approval(self, batch_id: str) -> PipelineStatus:
        stages: list[PipelineStageResult] = []
        started = datetime.utcnow()
        self.run_bronze(batch_id)
        stages.append(PipelineStageResult(stage="bronze_done", started_at=started, finished_at=datetime.utcnow()))
        started = datetime.utcnow()
        self.run_silver(batch_id)
        stages.append(PipelineStageResult(stage="silver_done", started_at=started, finished_at=datetime.utcnow()))
        started = datetime.utcnow()
        n = len(self.run_relationships(batch_id))
        stages.append(
            PipelineStageResult(
                stage="relationships_detected",
                started_at=started,
                finished_at=datetime.utcnow(),
                message=f"{n} suggestion(s); awaiting approval.",
            )
        )
        st = self.status(batch_id)
        st.stages = stages
        return st

    def run_bronze(self, batch_id: str) -> list[StoredBronzeTable]:
        self._require_batch(batch_id)
        store = FileBatchStore(batch_id)
        out: list[StoredBronzeTable] = []

        for f in store.list_files():
            read = read_file(f.stored_file_path)
            for frame_info in read.frames:
                table_name = safe_table_name(f"bronze_{frame_info.name}")
                frame = frame_info.frame
                now = datetime.utcnow()
                rows: list[dict[str, Any]] = []
                for idx, row in enumerate(frame.iter_rows(named=True), start=1):
                    values = [None if v is None else str(v) for v in row.values()]
                    rows.append({
                        "_bronze_id": idx,
                        "_batch_id": batch_id,
                        "_source_file_id": f.file_id,
                        "_source_file_name": f.original_file_name,
                        "_source_sheet_name": frame_info.sheet_name,
                        "_source_row_number": idx,
                        "_raw_record_hash": hash_record(values),
                        "_ingested_at": now.isoformat(),
                        **row,
                    })
                bronze_frame = pl.DataFrame(rows) if rows else pl.DataFrame()
                path = store.write_bronze_parquet(table_name, bronze_frame)
                table_id = store.next_id("bronze")
                rec = StoredBronzeTable(
                    id=table_id,
                    batch_id=batch_id,
                    file_id=f.file_id,
                    table_name=table_name,
                    source_file_name=f.original_file_name,
                    source_sheet_name=frame_info.sheet_name,
                    row_count=bronze_frame.height,
                    column_count=len(frame.columns),
                    parquet_path=str(path),
                )
                store.save_bronze_table(rec)
                out.append(rec)

                tp = self._profiler.profile_table(
                    batch_id=batch_id,
                    layer="bronze",
                    table_name=table_name,
                    frame=frame_info.frame,
                    original_column_names=frame_info.original_columns,
                    persist=False,
                )
                store.save_table_profile(tp)
                drafts = self._dq.run(
                    batch_id=batch_id, table_profile=tp, frame=frame_info.frame, persist=False,
                )
                store.save_quality_issues(drafts)

        store.set_stage("bronze_done")
        store.save_pipeline_step(
            "bronze", "done",
            message=f"{len(out)} table(s)",
            detail=", ".join(t.table_name for t in out[:5]),
        )
        return out

    def run_silver(self, batch_id: str) -> list[StoredSilverTable]:
        self._require_batch(batch_id)
        store = FileBatchStore(batch_id)
        out: list[StoredSilverTable] = []

        for bronze in store.list_bronze_tables():
            df = store.read_bronze_parquet(bronze.table_name)
            if df.is_empty():
                continue

            data_cols = [c for c in df.columns if c not in BRONZE_META]
            profiles = {
                c["column_name"]: c
                for c in store.list_column_profiles("bronze")
                if c["table_name"] == bronze.table_name
            }

            cleaned_by_col: dict[str, list[Any]] = {}
            for col in data_cols:
                cp = profiles.get(col, {})
                physical = cp.get("physical_type", "string")
                semantic = cp.get("semantic_type", "unknown")
                raw_values = df[col].to_list()
                cleaned, _stats = clean_column(
                    col, raw_values, physical_type=physical, semantic_type=semantic,
                )
                cleaned_by_col[col] = cleaned

            cleaned_rows: list[dict[str, Any]] = []
            seen: set[str] = set()
            for row in df.iter_rows(named=True):
                row_num = int(row["_source_row_number"])
                data_row = {c: cleaned_by_col[c][row_num - 1] for c in data_cols}
                row_hash = hash_record(list(data_row.values()))
                if row_hash in seen:
                    continue
                seen.add(row_hash)
                cleaned_rows.append({
                    "_silver_id": len(cleaned_rows) + 1,
                    "_batch_id": batch_id,
                    "_bronze_id": row["_bronze_id"],
                    "_source_file_id": row["_source_file_id"],
                    "_source_row_number": row_num,
                    "_clean_record_hash": row_hash,
                    "_quality_score": _row_quality(data_row),
                    "_cleaning_status": "cleaned",
                    "_cleaned_at": datetime.utcnow().isoformat(),
                    **data_row,
                })

            table_name = safe_table_name(f"silver_{bronze.table_name.removeprefix('bronze_')}")
            silver_frame = pl.DataFrame(cleaned_rows) if cleaned_rows else pl.DataFrame()
            path = store.write_silver_parquet(table_name, silver_frame)

            data_only = silver_frame.select(data_cols) if cleaned_rows else pl.DataFrame()
            tp = self._profiler.profile_table(
                batch_id=batch_id,
                layer="silver",
                table_name=table_name,
                frame=data_only,
                persist=False,
            )
            store.save_table_profile(tp)

            rec = StoredSilverTable(
                id=store.next_id("silver"),
                batch_id=batch_id,
                bronze_table_id=bronze.id,
                table_name=table_name,
                row_count=silver_frame.height,
                column_count=len(data_cols),
                dedup_removed_rows=df.height - silver_frame.height,
                quality_score=(
                    sum(r["_quality_score"] for r in cleaned_rows) / max(1, len(cleaned_rows))
                    if cleaned_rows else 0.0
                ),
                parquet_path=str(path),
            )
            store.save_silver_table(rec)
            out.append(rec)

        store.set_stage("silver_done")
        store.save_pipeline_step(
            "silver", "done",
            message=f"{len(out)} table(s)",
            detail=", ".join(t.table_name for t in out[:5]),
        )
        return out

    def run_relationships(self, batch_id: str) -> list[StoredRelationshipSuggestion]:
        self._require_batch(batch_id)
        store = FileBatchStore(batch_id)
        cols = _load_silver_column_refs(store)
        if len(cols) < 2:
            store.save_suggestions([])
            return []

        suggestions: list[StoredRelationshipSuggestion] = []
        sid = 0
        for i, a in enumerate(cols):
            for b in cols[i + 1:]:
                if a["table"] == b["table"]:
                    continue
                scored = _score_pair(store, a, b)
                if scored is None:
                    continue
                sid += 1
                suggestions.append(
                    StoredRelationshipSuggestion(id=sid, batch_id=batch_id, **scored)
                )

        store.save_suggestions(suggestions)
        store.set_stage("awaiting_approval")
        store.save_pipeline_step(
            "relationships", "done",
            message=f"{len(suggestions)} suggestion(s)",
        )
        return suggestions

    def run_gold(self, batch_id: str) -> list[StoredGoldTable]:
        self._require_batch(batch_id)
        store = FileBatchStore(batch_id)
        silvers = store.list_silver_tables()
        approved = store.list_approved()

        if not silvers:
            return []
        if len(silvers) > 1 and not approved:
            raise ApprovalRequiredError(
                "Gold cannot be built: no approved relationships and more than "
                "one Silver table exist. Approve at least one relationship first.",
                details={"silver_table_count": len(silvers)},
            )

        out: list[StoredGoldTable] = []
        for s in silvers:
            df = store.read_silver_parquet(s.table_name)
            gold_name = safe_table_name(f"gold_{s.table_name.removeprefix('silver_')}")
            path = store.write_gold_parquet(gold_name, df)
            rec = StoredGoldTable(
                id=store.next_id("gold"),
                batch_id=batch_id,
                table_name=gold_name,
                role="flat",
                row_count=df.height,
                column_count=len([c for c in df.columns if not c.startswith("_")]),
                source_silver_tables=s.table_name,
                parquet_path=str(path),
            )
            store.save_gold_table(rec)
            out.append(rec)

        store.set_stage("gold_done")
        store.save_pipeline_step(
            "gold", "done",
            message=f"{len(out)} table(s)",
            detail=", ".join(t.table_name for t in out[:5]),
        )
        return out

    def list_suggestions(self, batch_id: str) -> list[StoredRelationshipSuggestion]:
        return FileBatchStore(batch_id).list_suggestions()

    def list_approved(self, batch_id: str) -> list[StoredApprovedRelationship]:
        return FileBatchStore(batch_id).list_approved()

    def approve_relationship(
        self, batch_id: str, suggestion_id: int, *, decided_by: str, note: str | None = None,
    ) -> None:
        store = FileBatchStore(batch_id)
        suggestions = store.list_suggestions()
        sug = next((s for s in suggestions if s.id == suggestion_id), None)
        if sug is None:
            raise NotFoundError(f"Unknown suggestion id {suggestion_id}.")
        approved = store.list_approved()
        approved.append(
            StoredApprovedRelationship(
                id=store.next_id("approved"),
                batch_id=batch_id,
                source_table=sug.source_table,
                source_column=sug.source_column,
                target_table=sug.target_table,
                target_column=sug.target_column,
                relation_type=sug.suggested_relation_type,
                note=note,
                decided_by=decided_by,
                decided_at=datetime.utcnow().isoformat(),
            )
        )
        store.save_approved(approved)
        updated = []
        for s in suggestions:
            status = "approved" if s.id == suggestion_id else s.status
            updated.append(StoredRelationshipSuggestion(**{**s.__dict__, "status": status}))
        store.save_suggestions(updated)

    def reject_relationship(
        self, batch_id: str, suggestion_id: int, *, decided_by: str, note: str | None = None,
    ) -> None:
        del decided_by, note
        store = FileBatchStore(batch_id)
        suggestions = store.list_suggestions()
        updated = []
        for s in suggestions:
            status = "rejected" if s.id == suggestion_id else s.status
            updated.append(StoredRelationshipSuggestion(**{**s.__dict__, "status": status}))
        store.save_suggestions(updated)

    def list_quality_issues(self, batch_id: str) -> list[dict[str, Any]]:
        return FileBatchStore(batch_id).list_quality_issues()

    def list_column_profiles(self, batch_id: str) -> list[dict[str, Any]]:
        return FileBatchStore(batch_id).list_column_profiles()

    def export_parquet_bundle(self, batch_id: str, *, include_bronze: bool = True) -> dict[str, str]:
        """Copy bronze/silver/gold parquet into exports/parquet/ (same .parquet extension)."""
        import shutil

        store = FileBatchStore(batch_id)
        out_dir = settings.batch_exports_dir(batch_id) / "parquet"
        out_dir.mkdir(parents=True, exist_ok=True)
        artifacts: dict[str, str] = {}
        layers: list[tuple[str, object, object]] = []
        if include_bronze:
            layers.append(("bronze", store.list_bronze_tables, store.read_bronze_parquet))
        layers.extend([
            ("silver", store.list_silver_tables, store.read_silver_parquet),
            ("gold", store.list_gold_tables, store.read_gold_parquet),
        ])
        for layer, list_fn, _read_fn in layers:
            for t in list_fn():
                src = settings.batch_data_dir(batch_id) / layer / f"{t.table_name}.parquet"
                if not src.exists():
                    continue
                dest = out_dir / f"{layer}_{t.table_name}.parquet"
                shutil.copy2(src, dest)
                artifacts[f"{layer}:{t.table_name}"] = str(dest)
        return artifacts

    def export_csv_bundle(self, batch_id: str, *, include_bronze: bool = True) -> dict[str, str]:
        """Write bronze/silver/gold parquet tables as downloadable CSV files."""
        store = FileBatchStore(batch_id)
        out_dir = settings.batch_exports_dir(batch_id) / "csv"
        out_dir.mkdir(parents=True, exist_ok=True)
        artifacts: dict[str, str] = {}
        layers: list[tuple[str, object, object]] = []
        if include_bronze:
            layers.append(("bronze", store.list_bronze_tables, store.read_bronze_parquet))
        layers.extend([
            ("silver", store.list_silver_tables, store.read_silver_parquet),
            ("gold", store.list_gold_tables, store.read_gold_parquet),
        ])
        meta_cols = {c for c in ("_bronze_id", "_batch_id", "_source_file_id", "_source_file_name",
                                   "_source_sheet_name", "_source_row_number", "_raw_record_hash", "_ingested_at",
                                   "_silver_id", "_bronze_id", "_clean_record_hash", "_quality_score",
                                   "_cleaning_status", "_cleaned_at")}
        for layer, list_fn, read_fn in layers:
            for t in list_fn():
                df = read_fn(t.table_name)
                if df.is_empty():
                    continue
                data_cols = [c for c in df.columns if c not in meta_cols and not str(c).startswith("_")]
                export_df = df.select(data_cols) if data_cols else df
                path = out_dir / f"{layer}_{t.table_name}.csv"
                export_df.write_csv(path)
                artifacts[f"{layer}:{t.table_name}"] = str(path)
        return artifacts

    @staticmethod
    def _require_batch(batch_id: str) -> None:
        store = FileBatchStore(batch_id)
        if not store.load_batch() and not store.list_files():
            raise NotFoundError(f"Unknown batch_id '{batch_id}'.")


def _row_quality(row: dict[str, Any]) -> float:
    if not row:
        return 0.0
    non_null = sum(1 for v in row.values() if v is not None)
    return non_null / len(row)


def _load_silver_column_refs(store: FileBatchStore) -> list[dict[str, Any]]:
    profiles = store.list_table_profiles("silver")
    refs: list[dict[str, Any]] = []
    for tp in profiles:
        row_count = tp.get("row_count", 0)
        for c in tp.get("columns", []):
            if str(c.get("column_name", "")).startswith("_"):
                continue
            refs.append({
                "table": tp["table_name"],
                "column": c["column_name"],
                "original": c.get("original_column_name"),
                "physical_type": c.get("physical_type", "string"),
                "semantic_type": c.get("semantic_type", "unknown"),
                "null_percentage": c.get("null_percentage", 0.0),
                "unique_count": c.get("unique_count", 0),
                "row_count": row_count,
            })
    return refs


def _score_pair(
    store: FileBatchStore, a: dict[str, Any], b: dict[str, Any],
) -> dict[str, Any] | None:
    name_sim = SequenceMatcher(a=a["column"].lower(), b=b["column"].lower()).ratio()
    orig_sim = 0.0
    if a.get("original") and b.get("original"):
        orig_sim = SequenceMatcher(
            a=normalize_text(a["original"]).lower(),
            b=normalize_text(b["original"]).lower(),
        ).ratio()

    type_compat = 1.0 if _types_compatible(a["physical_type"], b["physical_type"]) else 0.0
    overlap, matching, dist_a, dist_b = _value_overlap_polars(store, a, b)
    card = max(
        (a["unique_count"] / a["row_count"]) if a["row_count"] else 0,
        (b["unique_count"] / b["row_count"]) if b["row_count"] else 0,
    )
    pattern_bonus = 1.0 if (_is_id_name(a["column"]) and _is_id_name(b["column"])) else 0.0

    confidence = min(
        1.0,
        max(
            0.0,
            0.20 * name_sim + 0.10 * orig_sim + 0.15 * type_compat
            + 0.30 * overlap + 0.10 * card + 0.05 * pattern_bonus,
        ),
    )
    if confidence < settings.relationship_min_confidence or overlap < settings.relationship_value_overlap_threshold:
        return None

    if b["unique_count"] / max(1, b["row_count"]) >= a["unique_count"] / max(1, a["row_count"]):
        src, tgt = a, b
    else:
        src, tgt = b, a

    return {
        "source_table": src["table"],
        "source_column": src["column"],
        "source_original_column": src.get("original"),
        "target_table": tgt["table"],
        "target_column": tgt["column"],
        "target_original_column": tgt.get("original"),
        "suggested_relation_type": "many_to_one",
        "confidence_score": confidence,
        "column_name_similarity_score": name_sim,
        "value_overlap_score": overlap,
        "data_type_compatibility_score": type_compat,
        "cardinality_score": card,
        "matching_values_count": matching,
        "source_distinct_count": dist_a,
        "target_distinct_count": dist_b,
        "source_null_percentage": src["null_percentage"],
        "target_null_percentage": tgt["null_percentage"],
        "risk_level": "low" if overlap >= 0.8 else "medium",
        "risk_reason": None,
        "recommendation": "Review and approve before Gold.",
        "status": "suggested",
    }


def _value_overlap_polars(
    store: FileBatchStore, a: dict[str, Any], b: dict[str, Any],
) -> tuple[float, int, int, int]:
    try:
        df_a = store.read_silver_parquet(a["table"]).select(a["column"]).drop_nulls()
        df_b = store.read_silver_parquet(b["table"]).select(b["column"]).drop_nulls()
        vals_a = df_a[a["column"]].cast(pl.Utf8).unique()
        vals_b = df_b[b["column"]].cast(pl.Utf8).unique()
        dist_a = vals_a.len()
        dist_b = vals_b.len()
        joined = vals_a.to_frame().join(vals_b.to_frame(), on=a["column"], how="inner")
        matching = joined.height
        denom = min(dist_a, dist_b) or 1
        return min(1.0, matching / denom), matching, dist_a, dist_b
    except Exception as exc:  # noqa: BLE001
        _log.debug("Polars overlap failed: %s", exc)
        return 0.0, 0, a["unique_count"], b["unique_count"]


def _types_compatible(a: str, b: str) -> bool:
    nums = {"integer", "float", "decimal"}
    strings = {"string", "text"}
    if a == b:
        return True
    if a in nums and b in nums:
        return True
    if a in strings and b in strings:
        return True
    return (a in nums and b in strings) or (b in nums and a in strings)


def _is_id_name(name: str) -> bool:
    n = name.lower()
    return any(p in n for p in _ID_PATTERNS) or n.endswith("_id") or n.endswith("id")
