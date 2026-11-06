from datetime import date
from decimal import Decimal

from psycopg import sql

from finance_agent.db.loader import Connection
from finance_agent.queries.spend import spend_by_category
from tests.helpers import ingest_file

TENANT = "demo-tenant"
MARCH_2026 = date(2026, 3, 1)


def _load(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_demo.json")


def _row_counts(conn: Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in ("raw_pulls", "accounts", "transactions"):
        query = sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
        row = conn.execute(query).fetchone()
        assert row is not None
        counts[table] = row[0]
    return counts


def test_groceries_spend_for_march_2026_is_exact(conn: Connection) -> None:
    _load(conn)

    result = spend_by_category(conn, TENANT, MARCH_2026, "groceries", "USD")

    # Hand-calculated from fixtures/simplefin_demo.json, groceries, March 2026:
    #   chk-txn-003  2026-03-09   -12.49
    #   cc-txn-002   2026-03-03   -84.17
    #   cc-txn-004   2026-03-14  -156.03
    #   cc-txn-006   2026-03-22   -47.88
    #   cc-txn-007   2026-03-24   +15.25  refund, nets against spend
    #   SUM = -285.32  ->  spend = -SUM = 285.32
    # Excluded: cc-txn-001 (2026-02-28 23:59:59 UTC, February),
    #           cc-txn-009 (2026-04-01 00:00:00 UTC, April),
    #           cc-txn-008 (-33.33, pending).
    assert isinstance(result, Decimal)
    assert result == Decimal("285.32")


def test_any_day_in_month_selects_that_month(conn: Connection) -> None:
    _load(conn)

    assert spend_by_category(conn, TENANT, date(2026, 3, 31), "groceries", "USD") == Decimal(
        "285.32"
    )


def test_loader_is_idempotent(conn: Connection) -> None:
    _load(conn)
    once = _row_counts(conn)
    _load(conn)

    assert _row_counts(conn) == once
    assert once == {"raw_pulls": 1, "accounts": 2, "transactions": 12}


def test_unknown_category_is_zero(conn: Connection) -> None:
    _load(conn)

    assert spend_by_category(conn, TENANT, MARCH_2026, "travel", "USD") == Decimal("0")


def test_other_tenant_sees_nothing(conn: Connection) -> None:
    _load(conn)

    assert spend_by_category(conn, "other-tenant", MARCH_2026, "groceries", "USD") == Decimal("0")
