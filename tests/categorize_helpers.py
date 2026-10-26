"""Shared builders for the categorization tests."""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime

from finance_agent.db.loader import Connection
from finance_agent.ingest.pipeline import ingest
from tests.helpers import UTC_TZ, pull_from_text

TENANT = "demo-tenant"
DAY = date(2026, 3, 10)


@dataclass(frozen=True)
class Txn:
    id: str
    desc: str
    amount: str = "-5.00"
    day: date = DAY
    pending: bool = False


def body(txns: list[Txn], account: str = "a") -> str:
    """A v2 body of plain transactions: no category hints, so only rules categorize."""
    return json.dumps(
        {
            "errlist": [],
            "connections": [{"conn_id": "C", "name": "Bank"}],
            "accounts": [
                {
                    "id": account,
                    "name": account,
                    "conn_id": "C",
                    "currency": "USD",
                    "balance": "0",
                    "balance-date": 1774958400,
                    "transactions": [
                        {
                            "id": t.id,
                            "posted": int(
                                datetime(
                                    t.day.year, t.day.month, t.day.day, 12, tzinfo=UTC
                                ).timestamp()
                            ),
                            "amount": t.amount,
                            "description": t.desc,
                            **({"pending": True} if t.pending else {}),
                        }
                        for t in txns
                    ],
                }
            ],
        }
    )


def load(conn: Connection, txns: list[Txn], tenant: str = TENANT) -> None:
    result = ingest(conn, tenant, pull_from_text(body(txns)), UTC_TZ)
    assert result.status == "ok", result.message


def state(conn: Connection) -> dict[str, tuple[str | None, str | None]]:
    """external id -> (category, category_source)."""
    rows = conn.execute(
        "SELECT external_id, category, category_source FROM transactions"
    ).fetchall()
    return {r[0]: (r[1], r[2]) for r in rows}


def keys(conn: Connection) -> dict[str, str | None]:
    rows = conn.execute("SELECT external_id, merchant_normalized FROM transactions").fetchall()
    return {r[0]: r[1] for r in rows}


def add_rule(
    conn: Connection, key: str, category: str, source: str = "user", tenant: str = TENANT
) -> None:
    conn.execute(
        """
        INSERT INTO merchant_rules (tenant_id, merchant_normalized, category, source)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (tenant_id, merchant_normalized)
        DO UPDATE SET category = EXCLUDED.category, source = EXCLUDED.source
        """,
        (tenant, key, category, source),
    )


def versions(conn: Connection, table: str) -> list[tuple[object, ...]]:
    """Every row's version (xmin); any write to a row changes it."""
    rows = conn.execute(f"SELECT xmin::text FROM {table} ORDER BY ctid").fetchall()  # noqa: S608
    return [tuple(r) for r in rows]
