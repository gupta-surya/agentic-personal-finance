"""The credentials zone (needs Postgres: run with `docker compose up -d`).

Round-trips through the encrypted table, proves tenant isolation (no fallback), and that the
stored bytes are ciphertext, not the plaintext access URL.
"""

from datetime import UTC, datetime
from pathlib import Path

from finance_agent.credentials import (
    delete_access_url,
    get_access_url,
    has_access_url,
    store_access_url,
)
from finance_agent.crypto import FileKeyStore
from finance_agent.db.loader import Connection

SENTINEL = "SENTINEL-ACCESS-URL-9921"
ACCESS = f"https://user:{SENTINEL}@bank.example.com/simplefin"
NOW = datetime(2026, 10, 25, tzinfo=UTC)


def test_store_and_get_round_trip(conn: Connection, tmp_path: Path) -> None:
    store = FileKeyStore(tmp_path / "keys.json")
    assert get_access_url(conn, "demo-tenant", store) is None
    store_access_url(conn, "demo-tenant", ACCESS, store, NOW)
    assert get_access_url(conn, "demo-tenant", store) == ACCESS
    assert has_access_url(conn, "demo-tenant") is True


def test_missing_tenant_returns_none_never_falls_back(conn: Connection, tmp_path: Path) -> None:
    store = FileKeyStore(tmp_path / "keys.json")
    store_access_url(conn, "demo-tenant", ACCESS, store, NOW)
    assert get_access_url(conn, "other-tenant", store) is None  # no cross-tenant fallback


def test_stored_bytes_are_ciphertext(conn: Connection, tmp_path: Path) -> None:
    store = FileKeyStore(tmp_path / "keys.json")
    store_access_url(conn, "demo-tenant", ACCESS, store, NOW)
    row = conn.execute(
        "SELECT ciphertext FROM credentials WHERE tenant_id = %s", ("demo-tenant",)
    ).fetchone()
    assert row is not None
    assert SENTINEL.encode() not in bytes(row[0])


def test_delete(conn: Connection, tmp_path: Path) -> None:
    store = FileKeyStore(tmp_path / "keys.json")
    store_access_url(conn, "demo-tenant", ACCESS, store, NOW)
    delete_access_url(conn, "demo-tenant")
    assert has_access_url(conn, "demo-tenant") is False
