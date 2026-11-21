"""The *_test database guard (pure)."""

import pytest

from finance_agent.provision import DatabaseIsTestError, guard_not_test_db


def test_rejects_a_test_database_by_name_or_url() -> None:
    with pytest.raises(DatabaseIsTestError):
        guard_not_test_db("finance_test")
    with pytest.raises(DatabaseIsTestError):
        guard_not_test_db("postgresql://finance:finance@127.0.0.1:5432/finance_test")


def test_allows_a_real_database() -> None:
    guard_not_test_db("finance")
    guard_not_test_db("postgresql://finance_app:pw@127.0.0.1:5432/finance")
