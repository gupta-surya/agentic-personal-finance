"""A ``SeriesCatalog`` over in-memory synthetic transactions, for building charts
without a database.

It plays the part Postgres plays in production, so it follows the catalog
conventions in ``queries/series.py``: ``end`` exclusive, rows bucketed by calendar
month of ``posted_date``, pending and internal-transfer rows excluded, one currency
per call, empty months omitted, rows ordered by month then category (uncategorized
last). Data is built from fixed formulas, never random, and ``result_id`` comes from
a per-instance counter, so the same calls always yield identical results.

All data is synthetic; none of it is real financial data.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from finance_agent.queries.result import (
    AMOUNTS_IN_DECIMAL,
    CashFlowRow,
    MonthlyCategorySpendRow,
    QueryResult,
)

INCOME_CATEGORIES = frozenset({"income"})
DEFAULT_AS_OF = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class SyntheticTransaction:
    posted: date
    amount: Decimal  # signed: debit negative, credit positive
    category: str | None
    currency: str = "USD"
    pending: bool = False
    internal_transfer: bool = False


def synthetic_transactions() -> list[SyntheticTransaction]:
    """Sep 2025 – Oct 2026 of a plausible household, plus the awkward cases:
    a refund (Mar 2026 groceries), an uncategorized charge (Mar 2026), a transfer
    pair (Feb 2026), a pending charge (Oct 2026) and a EUR charge (Mar 2026)."""
    txns: list[SyntheticTransaction] = []
    for i in range(14):
        year, month = 2025 + (8 + i) // 12, (8 + i) % 12 + 1

        def day(d: int, y: int = year, m: int = month) -> date:
            return date(y, m, d)

        def money(whole: int, cents: int) -> Decimal:
            return Decimal(f"{whole}.{cents:02d}")

        txns += [
            SyntheticTransaction(day(1), Decimal("3200.00"), "income"),
            SyntheticTransaction(day(3), Decimal("-1500.00"), "rent"),
            SyntheticTransaction(day(8), -money(150 + i * 37 % 90, i * 13 % 100), "groceries"),
            SyntheticTransaction(day(20), -money(120 + i * 53 % 80, i * 7 % 100), "groceries"),
            SyntheticTransaction(day(12), -money(60 + i * 29 % 70, 50), "dining"),
            SyntheticTransaction(day(16), -money(40 + i * 17 % 45, i * 11 % 100), "transport"),
        ]
    txns += [
        SyntheticTransaction(date(2026, 3, 15), Decimal("25.00"), "groceries"),
        SyntheticTransaction(date(2026, 3, 22), Decimal("-19.99"), None),
        SyntheticTransaction(date(2026, 3, 5), Decimal("-30.00"), "dining", currency="EUR"),
        SyntheticTransaction(date(2026, 2, 10), Decimal("-500.00"), None, internal_transfer=True),
        SyntheticTransaction(date(2026, 2, 10), Decimal("500.00"), None, internal_transfer=True),
        SyntheticTransaction(date(2026, 10, 24), Decimal("-50.00"), "dining", pending=True),
    ]
    return sorted(txns, key=lambda t: (t.posted, t.amount))


def _month(day: date) -> date:
    return day.replace(day=1)


class FakeSeriesCatalog:
    def __init__(
        self,
        transactions: list[SyntheticTransaction] | None = None,
        as_of: datetime = DEFAULT_AS_OF,
        data_version: str = "dv_fake_1",
    ) -> None:
        self._txns = synthetic_transactions() if transactions is None else transactions
        self._as_of = as_of
        self._data_version = data_version
        self._calls = 0

    def earliest_date(self) -> date | None:
        """First posted date, for the ``all_time`` period."""
        posted = [t.posted for t in self._txns if not t.pending and not t.internal_transfer]
        return min(posted) if posted else None

    def _next_result_id(self) -> str:
        self._calls += 1
        return f"res_fake_{self._calls}"

    def _posted(self, start: date, end: date, currency: str) -> list[SyntheticTransaction]:
        return [
            t
            for t in self._txns
            if start <= t.posted < end
            and t.currency == currency
            and not t.pending
            and not t.internal_transfer
        ]

    def monthly_spend_by_category(
        self, start: date, end: date, currency: str
    ) -> QueryResult[MonthlyCategorySpendRow]:
        spend: dict[tuple[date, str | None], Decimal] = defaultdict(Decimal)
        for t in self._posted(start, end, currency):
            if t.category not in INCOME_CATEGORIES:
                spend[_month(t.posted), t.category] -= t.amount
        keys = sorted(spend, key=lambda k: (k[0], k[1] is None, k[1] or ""))
        rows = [MonthlyCategorySpendRow(month=m, category=c, spend=spend[m, c]) for m, c in keys]
        return QueryResult[MonthlyCategorySpendRow](
            query="monthly_spend_by_category",
            params=self._params(start, end, currency),
            result_id=self._next_result_id(),
            data_version=self._data_version,
            as_of=self._as_of,
            amounts_in=AMOUNTS_IN_DECIMAL,
            rows=rows,
            totals={"spend": sum((r.spend for r in rows), Decimal(0))} if rows else {},
        )

    def cash_flow(self, start: date, end: date, currency: str) -> QueryResult[CashFlowRow]:
        inflow: dict[date, Decimal] = defaultdict(Decimal)
        outflow: dict[date, Decimal] = defaultdict(Decimal)
        for t in self._posted(start, end, currency):
            month = _month(t.posted)
            inflow[month] += max(t.amount, Decimal(0))
            outflow[month] += max(-t.amount, Decimal(0))
        rows = [
            CashFlowRow(month=m, inflow=inflow[m], outflow=outflow[m], net=inflow[m] - outflow[m])
            for m in sorted(inflow)
        ]
        totals = (
            {
                "inflow": sum((r.inflow for r in rows), Decimal(0)),
                "outflow": sum((r.outflow for r in rows), Decimal(0)),
                "net": sum((r.net for r in rows), Decimal(0)),
            }
            if rows
            else {}
        )
        return QueryResult[CashFlowRow](
            query="cash_flow",
            params=self._params(start, end, currency),
            result_id=self._next_result_id(),
            data_version=self._data_version,
            as_of=self._as_of,
            amounts_in=AMOUNTS_IN_DECIMAL,
            rows=rows,
            totals=totals,
        )

    @staticmethod
    def _params(start: date, end: date, currency: str) -> dict[str, str]:
        return {"start": start.isoformat(), "end": end.isoformat(), "currency": currency}
