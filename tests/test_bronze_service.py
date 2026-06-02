"""Tests for the pure helpers in BronzeService (no MySQL required)."""

from __future__ import annotations

import pytest

from app.services.bronze_service import BRONZE_META_COLUMNS


def test_bronze_meta_columns_present() -> None:
    required = {
        "_bronze_id", "_batch_id", "_source_file_id",
        "_source_file_name", "_source_sheet_name",
        "_source_row_number", "_raw_record_hash", "_ingested_at",
    }
    assert required.issubset(BRONZE_META_COLUMNS)


@pytest.mark.mysql
def test_bronze_ingest_end_to_end() -> None:
    pytest.skip("Covered by integration suite when RUN_MYSQL_TESTS=1")
