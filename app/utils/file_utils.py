"""Filesystem helpers: safe filenames, batch IDs, MIME detection."""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

_SAFE_FILENAME_RE: Final = re.compile(r"[^a-zA-Z0-9._\-]+")

KNOWN_EXTENSIONS: Final[dict[str, str]] = {
    ".csv": "csv",
    ".tsv": "csv",
    ".txt": "csv",
    ".xlsx": "excel",
    ".xlsm": "excel",
    ".xls": "excel",
    ".json": "json",
    ".jsonl": "json",
    ".ndjson": "json",
}


def new_batch_id() -> str:
    """Return a sortable, human-readable batch identifier."""
    now = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"b_{now}_{secrets.token_hex(3)}"


def new_file_id() -> str:
    return f"f_{uuid.uuid4().hex[:12]}"


def safe_filename(name: str, *, max_len: int = 100) -> str:
    """Sanitize a user-provided filename for safe filesystem storage."""
    name = Path(name).name  # strip directories defensively
    cleaned = _SAFE_FILENAME_RE.sub("_", name).strip("_.")
    if not cleaned:
        cleaned = "file"
    if len(cleaned) > max_len:
        stem = Path(cleaned).stem[: max_len - 10]
        suffix = Path(cleaned).suffix
        cleaned = f"{stem}{suffix}"
    return cleaned


def detect_file_format(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return KNOWN_EXTENSIONS.get(ext, "unknown")


def write_bytes(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path
