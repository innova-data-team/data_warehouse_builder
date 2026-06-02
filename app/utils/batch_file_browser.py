"""List and package all files belonging to a batch (for UI download)."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from app.core.config import settings

LAYER_ORDER = ("raw", "bronze", "silver", "gold", "export", "sql", "metadata")

MIME_BY_EXTENSION: dict[str, str] = {
    ".parquet": "application/vnd.apache.parquet",
    ".csv": "text/csv",
    ".json": "application/json",
    ".jsonl": "application/jsonl",
    ".ndjson": "application/x-ndjson",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".sql": "text/plain",
    ".txt": "text/plain",
}


@dataclass(frozen=True, slots=True)
class BatchFileInfo:
    """A single file on disk tied to a batch."""

    layer: str
    relative_path: str
    absolute_path: Path
    size_bytes: int
    extension: str

    @property
    def display_name(self) -> str:
        return self.relative_path.replace("\\", "/")

    @property
    def download_filename(self) -> str:
        """Basename with original extension preserved."""
        return Path(self.relative_path).name

    @property
    def download_mime(self) -> str:
        return mime_for_extension(self.extension)


def _scan_dir(layer: str, root: Path) -> list[BatchFileInfo]:
    if not root.exists():
        return []
    out: list[BatchFileInfo] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        out.append(
            BatchFileInfo(
                layer=layer,
                relative_path=rel,
                absolute_path=path,
                size_bytes=path.stat().st_size,
                extension=path.suffix.lower(),
            )
        )
    return out


def list_batch_files(batch_id: str) -> list[BatchFileInfo]:
    """Collect every file for a batch across raw, pipeline, exports, and SQL."""
    files: list[BatchFileInfo] = []

    files.extend(_scan_dir("raw", settings.batch_raw_dir(batch_id)))

    batch_root = settings.batch_data_dir(batch_id)
    for sub, layer in (("bronze", "bronze"), ("silver", "silver"), ("gold", "gold")):
        files.extend(_scan_dir(layer, batch_root / sub))

    for name in (
        "batch.json", "files.json", "bronze_tables.json", "silver_tables.json",
        "gold_tables.json", "quality_issues.json",
    ):
        p = batch_root / name
        if p.is_file():
            files.append(
                BatchFileInfo(
                    layer="metadata",
                    relative_path=name,
                    absolute_path=p,
                    size_bytes=p.stat().st_size,
                    extension=p.suffix.lower(),
                )
            )

    files.extend(_scan_dir("metadata", batch_root / "profiles"))
    files.extend(_scan_dir("metadata", batch_root / "relationships"))
    files.extend(_scan_dir("export", settings.batch_exports_dir(batch_id)))
    files.extend(_scan_dir("sql", settings.batch_sql_dir(batch_id)))

    files.sort(key=lambda f: (LAYER_ORDER.index(f.layer) if f.layer in LAYER_ORDER else 99, f.relative_path))
    return files


def mime_for_extension(ext: str) -> str:
    return MIME_BY_EXTENSION.get(ext.lower(), "application/octet-stream")


def read_file_bytes(path: Path) -> bytes:
    return path.read_bytes()


def download_payload(info: BatchFileInfo) -> tuple[bytes, str, str]:
    """Return (bytes, filename, mime) — always keeps the file's original extension."""
    return read_file_bytes(info.absolute_path), info.download_filename, info.download_mime


def parquet_to_csv_bytes(path: Path) -> bytes:
    """Convert a parquet file to CSV bytes for browser download."""
    df = pl.read_parquet(path)
    buf = io.BytesIO()
    df.write_csv(buf)
    return buf.getvalue()


def build_batch_zip(batch_id: str, *, layers: set[str] | None = None) -> bytes:
    """Zip batch files with original names and extensions (parquet stays .parquet)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for info in list_batch_files(batch_id):
            if layers and info.layer not in layers:
                continue
            arcname = f"{info.layer}/{info.relative_path}"
            zf.write(info.absolute_path, arcname)
    buf.seek(0)
    return buf.read()


def build_batch_zip_as_csv(batch_id: str, *, layers: set[str] | None = None) -> bytes:
    """Zip with .parquet files converted to .csv (optional export format)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for info in list_batch_files(batch_id):
            if layers and info.layer not in layers:
                continue
            arcname = f"{info.layer}/{info.relative_path}"
            if info.extension == ".parquet":
                csv_arc = arcname.replace(".parquet", ".csv")
                zf.writestr(csv_arc, parquet_to_csv_bytes(info.absolute_path))
            else:
                zf.write(info.absolute_path, arcname)
    buf.seek(0)
    return buf.read()


def parquet_file_infos(batch_id: str) -> list[BatchFileInfo]:
    """All .parquet tables (bronze / silver / gold + export/parquet copies)."""
    return [f for f in list_batch_files(batch_id) if f.extension == ".parquet"]


def cleaned_file_infos(batch_id: str) -> list[BatchFileInfo]:
    """Pipeline outputs: bronze / silver / gold parquet (+ optional CSV exports)."""
    return [
        f for f in list_batch_files(batch_id)
        if f.layer in ("bronze", "silver", "gold")
        or (f.layer == "export" and f.extension in (".csv", ".parquet"))
    ]
