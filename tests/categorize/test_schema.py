"""Migration 0006: merchant key column, pg_trgm and the trigram index."""

from typing import Any

from finance_agent.db.loader import Connection
from tests.helpers import ingest_file

TENANT = "demo-tenant"


def _one(conn: Connection, query: str, *params: object) -> tuple[Any, ...]:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return tuple(row)


def test_pg_trgm_is_installed_by_the_migration_after_every_reset(conn: Connection) -> None:
    # The `conn` fixture drops the public schema (and the extension) before each test, so
    # this only holds if the migration creates the extension itself.
    assert _one(conn, "SELECT count(*) FROM pg_extension WHERE extname = 'pg_trgm'") == (1,)
    similarity = _one(conn, "SELECT similarity('STARBUCKS', 'STARBUCKS')")[0]
    assert similarity == 1.0


def test_the_trigram_index_exists_on_merchant_rules(conn: Connection) -> None:
    definition = _one(
        conn,
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'merchant_rules_merchant_trgm_idx'",
    )[0]

    assert "USING gin" in definition and "gin_trgm_ops" in definition
    assert "merchant_normalized" in definition


def test_transactions_start_with_no_merchant_key(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_demo.json")

    assert _one(
        conn, "SELECT count(*) FILTER (WHERE merchant_normalized IS NOT NULL) FROM transactions"
    ) == (0,)
