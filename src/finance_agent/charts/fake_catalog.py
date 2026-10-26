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
from typing import Any

from finance_agent.queries.result import (
    AMOUNTS_IN_DECIMAL,
    CashFlowRow,
    MonthlyCategorySpendRow,
    QueryResult,
    ScalarRow,
    SpendBreakdownRow,
)
from finance_agent.queries.series import BreakdownGroupBy, KpiMeasure

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

    def _range_spend(self, start: date, end: date, currency: str) -> dict[str | None, Decimal]:
        """Net spend per category over the whole range (income categories excluded)."""
        totals: dict[str | None, Decimal] = defaultdict(Decimal)
        for t in self._posted(start, end, currency):
            if t.category not in INCOME_CATEGORIES:
                totals[t.category] -= t.amount
        return totals

    def monthly_spend_by_category(
        self, start: date, end: date, currency: str, top_n: int | None = None
    ) -> QueryResult[MonthlyCategorySpendRow]:
        kept = (
            None if top_n is None else _top_groups(self._range_spend(start, end, currency), top_n)
        )
        spend: dict[tuple[date, str | None, bool], Decimal] = defaultdict(Decimal)
        for t in self._posted(start, end, currency):
            if t.category in INCOME_CATEGORIES:
                continue
            folded = kept is not None and t.category not in kept
            spend[_month(t.posted), None if folded else t.category, folded] -= t.amount
        keys = sorted(spend, key=lambda k: (k[0], k[2], k[1] is None, k[1] or ""))
        rows = [
            MonthlyCategorySpendRow(month=m, category=c, spend=spend[m, c, other], is_other=other)
            for m, c, other in keys
        ]
        return QueryResult[MonthlyCategorySpendRow](
            query="monthly_spend_by_category",
            params=self._params(start, end, currency, top_n=top_n),
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

    def spend_breakdown(
        self,
        start: date,
        end: date,
        currency: str,
        group_by: BreakdownGroupBy = "category",
        top_n: int | None = None,
    ) -> QueryResult[SpendBreakdownRow]:
        by_group = self._range_spend(start, end, currency)
        total = sum(by_group.values(), Decimal(0))
        kept = set(by_group) if top_n is None else _top_groups(by_group, top_n)
        amounts: list[tuple[str | None, Decimal, bool]] = [
            (g, a, False) for g, a in by_group.items() if g in kept
        ]
        folded = sum((a for g, a in by_group.items() if g not in kept), Decimal(0))
        amounts.sort(key=lambda r: (-r[1], r[0] is None, r[0] or ""))
        if len(kept) < len(by_group):
            amounts.append((None, folded, True))
        rows = [
            SpendBreakdownRow(group=g, amount=a, share=_share(a, total), is_other=other)
            for g, a, other in amounts
        ]
        return QueryResult[SpendBreakdownRow](
            query="spend_breakdown",
            params=self._params(start, end, currency, group_by=group_by, top_n=top_n),
            result_id=self._next_result_id(),
            data_version=self._data_version,
            as_of=self._as_of,
            amounts_in=AMOUNTS_IN_DECIMAL,
            rows=rows,
            totals={"spend": total} if rows else {},
        )

    def kpi(
        self,
        measure: KpiMeasure,
        start: date,
        end: date,
        currency: str,
        category: str | None = None,
    ) -> QueryResult[ScalarRow]:
        if category is not None and measure != "spend":
            raise ValueError("category applies only to the spend measure")
        spend = self._range_spend(start, end, currency)
        income = sum(
            (
                t.amount
                for t in self._posted(start, end, currency)
                if t.category in INCOME_CATEGORIES
            ),
            Decimal(0),
        )
        total_spend = (
            spend.get(category, Decimal(0)) if category else sum(spend.values(), Decimal(0))
        )
        value = {"spend": total_spend, "income": income, "net": income - total_spend}[measure]
        return QueryResult[ScalarRow](
            query="kpi",
            params=self._params(start, end, currency, measure=measure, category=category),
            result_id=self._next_result_id(),
            data_version=self._data_version,
            as_of=self._as_of,
            amounts_in=AMOUNTS_IN_DECIMAL,
            value=value,
        )

    @staticmethod
    def _params(start: date, end: date, currency: str, **extra: str | int | None) -> dict[str, Any]:
        params: dict[str, Any] = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "currency": currency,
        }
        params.update({k: v for k, v in extra.items() if v is not None})
        return params


def _top_groups(totals: dict[str | None, Decimal], top_n: int) -> set[str | None]:
    """The N groups with the largest net spend; ties by name, uncategorized last."""
    if top_n < 1:
        raise ValueError("top_n must be at least 1")
    ranked = sorted(totals, key=lambda g: (-totals[g], g is None, g or ""))
    return set(ranked[:top_n])


def _share(amount: Decimal, total: Decimal) -> Decimal:
    return (amount / total).quantize(Decimal("0.0001")) if total else Decimal("0")
