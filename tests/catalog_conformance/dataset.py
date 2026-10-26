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


ZERO_DAY = date(2027, 1, 15)  # a zero-amount posted row alone in its month
UNCAT_DAYS = (date(2027, 2, 9), date(2027, 2, 10))  # uncategorized outranks a named category
HALF_DAY = date(2027, 3, 10)  # shares land on a half boundary: 1/20000 and 19999/20000
MONTH_END = (date(2027, 4, 30), date(2027, 5, 1))  # the last day of a month and the next first


def _edge_rows() -> list[SyntheticTransaction]:
    """Rows in months of their own (after the main data), each probing one edge."""
    return [
        SyntheticTransaction(ZERO_DAY, Decimal("0.00"), None),
        # the named category is earlier in the data, so it is the one folded by top_n=1
        SyntheticTransaction(UNCAT_DAYS[0], Decimal("-30.00"), "groceries"),
        SyntheticTransaction(UNCAT_DAYS[1], Decimal("-400.00"), None),
        SyntheticTransaction(HALF_DAY, Decimal("-1.00"), "dining"),
        SyntheticTransaction(HALF_DAY, Decimal("-19999.00"), "rent"),
        SyntheticTransaction(MONTH_END[0], Decimal("-12.00"), "dining"),
        SyntheticTransaction(MONTH_END[1], Decimal("-7.00"), "dining"),
    ]


def _earliest_traps() -> list[SyntheticTransaction]:
    """A pending row and a transfer pair dated before every real row, so earliest_date()
    only gives the right answer if it skips them."""
    return [
        SyntheticTransaction(date(2025, 1, 5), Decimal("-9.00"), "dining", pending=True),
        SyntheticTransaction(date(2025, 2, 3), Decimal("-300.00"), None, internal_transfer=True),
        SyntheticTransaction(date(2025, 2, 3), Decimal("300.00"), None, internal_transfer=True),
    ]


def dataset() -> list[Row]:
    rows = []
    extra = [*_tie_rows(), *_edge_rows(), *_earliest_traps()]
    for txn in [*synthetic_transactions(), *extra]:
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
    pairs = sum(1 for r in rows if r.txn.internal_transfer and r.txn.amount > 0)
    assert reconciled.matched == pairs == 2, "the dataset has exactly two transfer pairs"
    return PostgresSeriesCatalog(conn, tenant_id)
