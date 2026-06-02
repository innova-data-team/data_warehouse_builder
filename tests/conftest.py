"""Pytest fixtures shared across the test suite.

These tests are written to run **without a live MySQL** by exercising the
pure-Python utility / service code (file reader, normalization, type
detection, SQL generators). Tests that need MySQL are marked with
``@pytest.mark.mysql`` and skipped unless the env var ``RUN_MYSQL_TESTS``
is set.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    if os.getenv("RUN_MYSQL_TESTS"):
        return
    skip_mysql = pytest.mark.skip(reason="needs MySQL; set RUN_MYSQL_TESTS=1 to enable")
    for item in items:
        if "mysql" in item.keywords:
            item.add_marker(skip_mysql)


@pytest.fixture()
def tmp_csv(tmp_path: Path) -> Path:
    p = tmp_path / "sample.csv"
    p.write_text(
        "id,name,amount\n1,Alice,100\n2,Bob,200\n3,Sara,300\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture()
def tmp_arabic_csv(tmp_path: Path) -> Path:
    p = tmp_path / "patients.csv"
    p.write_text(
        "رقم المريض,اسم المريض,إجمالي الفاتورة\n"
        "1,محمد,1000\n2,Sarah,٢٬٥٠٠\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture()
def tmp_json(tmp_path: Path) -> Path:
    p = tmp_path / "sample.json"
    p.write_text(
        '[{"id": 1, "user": {"name": "Alice"}}, {"id": 2, "user": {"name": "Bob"}}]',
        encoding="utf-8",
    )
    return p
