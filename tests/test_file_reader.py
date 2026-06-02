"""Tests for the multi-format file reader."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.file_reader_service import read_file


def test_reads_csv_with_ascii_headers(tmp_csv: Path) -> None:
    result = read_file(tmp_csv)
    assert result.file_type == "csv"
    assert len(result.frames) == 1
    frame = result.frames[0].frame
    assert frame.shape == (3, 3)
    assert frame.columns == ["id", "name", "amount"]
    assert result.detected_encoding in {"utf-8", "utf-8-sig"}
    assert result.detected_delimiter == ","


def test_reads_csv_with_arabic_headers(tmp_arabic_csv: Path) -> None:
    result = read_file(tmp_arabic_csv)
    fi = result.frames[0]
    # Arabic headers should be transliterated to ASCII snake_case
    assert all(col.isascii() for col in fi.frame.columns)
    # original Arabic names preserved
    assert any("رقم" in c for c in fi.original_columns)
    assert fi.frame.shape[0] == 2


def test_reads_json_with_nested_object(tmp_json: Path) -> None:
    result = read_file(tmp_json)
    fi = result.frames[0]
    # nested user.name should be flattened
    assert any(c.endswith("name") for c in fi.frame.columns)
    assert fi.frame.shape[0] == 2


def test_unsupported_extension(tmp_path: Path) -> None:
    bad = tmp_path / "x.bin"
    bad.write_bytes(b"\x00\x01")
    with pytest.raises(Exception):
        read_file(bad)
