"""``SeriesCatalog`` over Postgres: the real implementation behind the fake.

Constructed with ``(conn, tenant_id)``. Read-only, tenant-scoped, parameterized SQL.
It follows the conventions in ``queries/series.py`` and agrees with
``charts.fake_catalog.FakeSeriesCatalog`` on the same data; a conformance suite in
``tests/catalog_conformance`` enforces that.

One row filter applies everywhere: posted rows (not pending), not an internal
transfer, in an account whose role counts toward cash flow (``on_budget`` or
``credit``), in the requested ISO currency, with ``posted_date`` in ``[start, end)``.
Closed accounts still count. Income is the category's ``is_income`` flag, never its
name. SQL does the grouping and summing; ordering, folding and rounding use the shared
rules in ``series_rules`` so they cannot drift from the fake.
"""

import uuid
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from finance_agent.db.loader import Connection
from finance_agent.queries.meta import data_stamp
from finance_agent.queries.result import (
    AMOUNTS_IN_DECIMAL,
    CashFlowRow,
    MonthlyCategorySpendRow,
    QueryResult,
    ScalarRow,
    SpendBreakdownRow,
)
from finance_agent.queries.series import BreakdownGroupBy, KpiMeasure
from finance_agent.queries.series_rules import catalog_params, share, top_groups

# Shared by every query: the FROM/JOIN and the row filter. Parameters, in order:
# tenant_id, currency, start, end.
_ROWS = """
    FROM transactions t
    JOIN accounts a ON a.tenant_id = t.tenant_id AND a.id = t.account_id
    LEFT JOIN categories c ON c.tenant_id = t.tenant_id AND c.name = t.category
    WHERE t.tenant_id = %s
      AND NOT t.pending
      AND t.posted_date IS NOT NULL
      AND NOT t.is_internal_transfer
      AND a.role IN ('on_budget', 'credit')
      AND a.currency_kind = 'iso'
      AND a.currency = %s
      AND t.posted_date >= %s
      AND t.posted_date < %s
"""

_SPEND_BY_MONTH_AND_CATEGORY = (
    "SELECT date_trunc('month', t.posted_date)::date, t.category, -SUM(t.amount) "
    + _ROWS
    + " AND NOT COALESCE(c.is_income, false) GROUP BY 1, 2"
)
_INCOME_TOTAL = "SELECT COALESCE(SUM(t.amount), 0) " + _ROWS + " AND COALESCE(c.is_income, false)"
_FLOW_BY_MONTH = (
    "SELECT date_trunc('month', t.posted_date)::date, "
    "COALESCE(SUM(t.amount) FILTER (WHERE t.amount > 0), 0), "
    "COALESCE(-SUM(t.amount) FILTER (WHERE t.amount < 0), 0) " + _ROWS + " GROUP BY 1 ORDER BY 1"
)
_EARLIEST = """
    SELECT min(t.posted_date)
    FROM transactions t
    JOIN accounts a ON a.tenant_id = t.tenant_id AND a.id = t.account_id
    WHERE t.tenant_id = %s
      AND NOT t.pending
      AND t.posted_date IS NOT NULL
      AND NOT t.is_internal_transfer
      AND a.role IN ('on_budget', 'credit')
"""


class PostgresSeriesCatalog:
    def __init__(self, conn: Connection, tenant_id: str) -> None:
        self._conn = conn
        self._tenant = tenant_id

    def earliest_date(self) -> date | None:
        """First posted date, for the ``all_time`` period (not part of the Protocol)."""
        row = self._conn.execute(_EARLIEST, (self._tenant,)).fetchone()
        assert row is not None
        return row[0]  # type: ignore[no-any-return]

    # --- aggregates (SQL) ---------------------------------------------------

    def _args(self, start: date, end: date, currency: str) -> tuple[str, str, date, date]:
        return (self._tenant, currency, start, end)

    def _spend_by_month_and_category(
        self, start: date, end: date, currency: str
    ) -> dict[tuple[date, str | None], Decimal]:
        rows = self._conn.execute(
            _SPEND_BY_MONTH_AND_CATEGORY, self._args(start, end, currency)
        ).fetchall()
        return {(month, category): Decimal(spend) for month, category, spend in rows}

    @staticmethod
    def _range_spend(
        by_month: dict[tuple[date, str | None], Decimal],
    ) -> dict[str | None, Decimal]:
        totals: dict[str | None, Decimal] = defaultdict(Decimal)
        for (_, category), spend in by_month.items():
            totals[category] += spend
        return totals

    def _envelope(self) -> tuple[str, str, datetime]:
        data_version, as_of = data_stamp(self._conn, self._tenant)
        return uuid.uuid4().hex, data_version, as_of

    # --- the Protocol -------------------------------------------------------

    def monthly_spend_by_category(
        self, start: date, end: date, currency: str, top_n: int | None = None
    ) -> QueryResult[MonthlyCategorySpendRow]:
        by_month = self._spend_by_month_and_category(start, end, currency)
        kept = None if top_n is None else top_groups(self._range_spend(by_month), top_n)
        spend: dict[tuple[date, str | None, bool], Decimal] = defaultdict(Decimal)
        for (month, category), amount in by_month.items():
            folded = kept is not None and category not in kept
            spend[month, None if folded else category, folded] += amount
        keys = sorted(spend, key=lambda k: (k[0], k[2], k[1] is None, k[1] or ""))
        rows = [
            MonthlyCategorySpendRow(month=m, category=c, spend=spend[m, c, other], is_other=other)
            for m, c, other in keys
        ]
        result_id, data_version, as_of = self._envelope()
        return QueryResult[MonthlyCategorySpendRow](
            query="monthly_spend_by_category",
            params=catalog_params(start, end, currency, top_n=top_n),
            result_id=result_id,
            data_version=data_version,
            as_of=as_of,
            amounts_in=AMOUNTS_IN_DECIMAL,
            rows=rows,
            totals={"spend": sum((r.spend for r in rows), Decimal(0))} if rows else {},
        )

    def cash_flow(self, start: date, end: date, currency: str) -> QueryResult[CashFlowRow]:
        flows = self._conn.execute(_FLOW_BY_MONTH, self._args(start, end, currency)).fetchall()
        rows = [
            CashFlowRow(
                month=month,
                inflow=Decimal(inflow),
                outflow=Decimal(outflow),
                net=Decimal(inflow) - Decimal(outflow),
            )
            for month, inflow, outflow in flows
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
        result_id, data_version, as_of = self._envelope()
        return QueryResult[CashFlowRow](
            query="cash_flow",
            params=catalog_params(start, end, currency),
            result_id=result_id,
            data_version=data_version,
            as_of=as_of,
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
        by_group = self._range_spend(self._spend_by_month_and_category(start, end, currency))
        total = sum(by_group.values(), Decimal(0))
        kept = set(by_group) if top_n is None else top_groups(by_group, top_n)
        amounts: list[tuple[str | None, Decimal, bool]] = [
            (g, a, False) for g, a in by_group.items() if g in kept
        ]
        folded = sum((a for g, a in by_group.items() if g not in kept), Decimal(0))
        amounts.sort(key=lambda r: (-r[1], r[0] is None, r[0] or ""))
        if len(kept) < len(by_group):
            amounts.append((None, folded, True))
        rows = [
            SpendBreakdownRow(group=g, amount=a, share=share(a, total), is_other=other)
            for g, a, other in amounts
        ]
        result_id, data_version, as_of = self._envelope()
        return QueryResult[SpendBreakdownRow](
            query="spend_breakdown",
            params=catalog_params(start, end, currency, group_by=group_by, top_n=top_n),
            result_id=result_id,
            data_version=data_version,
            as_of=as_of,
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
        spend = self._range_spend(self._spend_by_month_and_category(start, end, currency))
        income_row = self._conn.execute(_INCOME_TOTAL, self._args(start, end, currency)).fetchone()
        assert income_row is not None
        income = Decimal(income_row[0])
        total_spend = (
            spend.get(category, Decimal(0))
            if category is not None
            else sum(spend.values(), Decimal(0))
        )
        value = {"spend": total_spend, "income": income, "net": income - total_spend}[measure]
        result_id, data_version, as_of = self._envelope()
        return QueryResult[ScalarRow](
            query="kpi",
            params=catalog_params(start, end, currency, measure=measure, category=category),
            result_id=result_id,
            data_version=data_version,
            as_of=as_of,
            amounts_in=AMOUNTS_IN_DECIMAL,
            value=value,
        )
