"""One neutral dataset that both catalog implementations are loaded from.

It is built from the fake's own ``synthetic_transactions()`` (the fake's data stays the
reference), with each row assigned to an account: most in ``checking`` (USD), the EUR row
in ``euro``, and the Feb 10 transfer pair split across ``checking`` and ``savings``.
"""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from finance_agent.charts.fake_catalog import (
    FakeSeriesCatalog,
    SyntheticTransaction,
    synthetic_transactions,
)
from finance_agent.db.loader import Connection
from finance_agent.ingest.pipeline import ingest
from finance_agent.queries.pg_catalog import PostgresSeriesCatalog
from finance_agent.reconcile.match import reconcile
from tests.helpers import UTC_TZ, pull_from_text


@dataclass(frozen=True)
class Row:
    txn: SyntheticTransaction
    account: str


TIE_DAY = date(2026, 6, 25)


def _tie_rows() -> list[SyntheticTransaction]:
    """One day where dining, transport and uncategorized spend exactly the same, so
    tie-breaking (by name, uncategorized last) is exercised, plus one larger group."""
    return [
        SyntheticTransaction(TIE_DAY, Decimal("-55.00"), "groceries"),
        SyntheticTransaction(TIE_DAY, Decimal("-40.00"), "dining"),
        SyntheticTransaction(TIE_DAY, Decimal("-40.00"), "transport"),
        SyntheticTransaction(TIE_DAY, Decimal("-40.00"), None),
    ]


def dataset() -> list[Row]:
    rows = []
    for txn in [*synthetic_transactions(), *_tie_rows()]:
        if txn.currency != "USD":
            account = "euro"
        elif txn.internal_transfer and txn.amount > 0:
            account = "savings"
        else:
            account = "checking"
        rows.append(Row(txn, account))
    return rows


def to_fake(rows: list[Row]) -> FakeSeriesCatalog:
    return FakeSeriesCatalog([r.txn for r in rows])


def _noon(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=UTC).timestamp())


def simplefin_body(rows: list[Row]) -> str:
    """The dataset as a SimpleFIN v2 body: one connection, one account per name."""
    by_account: dict[str, list[dict[str, object]]] = {}
    currencies: dict[str, str] = {}
    for n, row in enumerate(rows):
        txn = row.txn
        entry: dict[str, object] = {
            "id": f"t{n}",
            # A pending row may carry a real date (SimpleFIN only says it *may* be 0), so
            # excluding it must come from the pending flag, not from a missing date.
            "posted": _noon(txn.posted),
            "amount": format(txn.amount, "f"),
            "description": f"TXN {n}",  # carries no transfer word on purpose
        }
        if txn.pending:
            entry["pending"] = True
        if txn.category is not None:
            entry["extra"] = {"category": txn.category}
        by_account.setdefault(row.account, []).append(entry)
        currencies[row.account] = txn.currency
    return json.dumps(
        {
            "errlist": [],
            "connections": [{"conn_id": "C", "name": "Demo Bank"}],
            "accounts": [
                {
                    "id": name,
                    "name": name,
                    "conn_id": "C",
                    "currency": currencies[name],
                    "balance": "0",
                    "balance-date": 1774958400,
                    "transactions": txns,
                }
                for name, txns in by_account.items()
            ],
        }
    )


def to_postgres(conn: Connection, tenant_id: str, rows: list[Row]) -> PostgresSeriesCatalog:
    """Ingest the dataset and reconcile it, so the real transfer logic is part of the test."""
    result = ingest(conn, tenant_id, pull_from_text(simplefin_body(rows)), UTC_TZ)
    assert result.status == "ok", result.message
    reconciled = reconcile(conn, tenant_id)
    assert reconciled.matched == 1, "the dataset has exactly one transfer pair"
    return PostgresSeriesCatalog(conn, tenant_id)
