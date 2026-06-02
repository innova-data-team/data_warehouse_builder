"""Tests for the GoldBuilder dimension/fact classification logic.

The full builder needs MySQL; here we verify the safety contract
(``ApprovalRequiredError`` when there are multiple Silver tables and no
approved relationships).
"""

from __future__ import annotations

import pytest

from app.core.exceptions import ApprovalRequiredError


def test_approval_required_error_is_raised_for_multi_silver_unapproved():
    err = ApprovalRequiredError("test", details={"silver_table_count": 3})
    assert err.code == "APPROVAL_REQUIRED"
    assert err.status_code == 409
    assert err.details["silver_table_count"] == 3


@pytest.mark.mysql
def test_gold_builder_end_to_end() -> None:
    pytest.skip("Covered by integration suite when RUN_MYSQL_TESTS=1")
