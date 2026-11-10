"""Role/database creation SQL via a fake admin connection; the *_test guard; URL + password."""

import pytest

from finance_agent.cli.database import (
    app_database_url,
    ensure_role_and_database,
    random_password,
)
from finance_agent.provision import DatabaseIsTestError


class _Cur:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self._row = row

    def fetchone(self) -> tuple[object, ...] | None:
        return self._row


class FakeAdminConn:
    def __init__(self, role_exists: bool = False, db_exists: bool = False) -> None:
        self.role_exists = role_exists
        self.db_exists = db_exists
        self.statements: list[str] = []

    def execute(self, query: object, params: object = None) -> _Cur:
        if isinstance(query, str):
            text = query
        else:
            try:
                text = query.as_string(None)  # type: ignore[attr-defined]
            except Exception:
                text = repr(query)
        self.statements.append(text)
        if "pg_roles" in text:
            return _Cur((1,) if self.role_exists else None)
        if "pg_database" in text:
            return _Cur((1,) if self.db_exists else None)
        return _Cur(None)


def test_creates_role_and_database_when_absent() -> None:
    conn = FakeAdminConn(role_exists=False, db_exists=False)
    ensure_role_and_database(conn, password="pw")  # type: ignore[arg-type]
    joined = " | ".join(conn.statements)
    assert "CREATE ROLE" in joined
    assert "CREATE DATABASE" in joined


def test_alters_role_and_skips_db_when_present() -> None:
    conn = FakeAdminConn(role_exists=True, db_exists=True)
    ensure_role_and_database(conn, password="pw")  # type: ignore[arg-type]
    joined = " | ".join(conn.statements)
    assert "ALTER ROLE" in joined
    assert "CREATE DATABASE" not in joined


def test_refuses_a_test_database() -> None:
    with pytest.raises(DatabaseIsTestError):
        ensure_role_and_database(FakeAdminConn(), database="finance_test", password="pw")  # type: ignore[arg-type]


def test_url_and_password() -> None:
    assert random_password(16).isalnum()
    assert len(random_password(24)) == 24
    url = app_database_url("secret", database="finance", role="finance_app")
    assert url == "postgresql://finance_app:secret@127.0.0.1:5432/finance"
