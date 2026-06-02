"""Stable hashing helpers used by Bronze/Silver record hashes and IDs."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

_CHUNK = 1024 * 1024  # 1 MiB


def hash_file_sha256(path: str | Path) -> str:
    """Return the SHA-256 digest of a file as a lowercase hex string."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def hash_record(values: Iterable[object]) -> str:
    """Stable SHA-1 hash of a row, using ``\\x1f`` (US) as field separator."""
    h = hashlib.sha1()
    sep = b"\x1f"
    for v in values:
        if v is None:
            h.update(b"\x00")
        else:
            h.update(str(v).encode("utf-8", errors="replace"))
        h.update(sep)
    return h.hexdigest()


def short_hash(value: str, length: int = 8) -> str:
    """Short stable hash useful for disambiguating collisions in identifiers."""
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]
