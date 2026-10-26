"""The series queries charts need, as one catalog interface. Types only.

The real implementation is constructed with ``(conn, tenant_id)`` and exposes
these methods, so callers and the frontend contract never see a database
connection. This module deliberately imports nothing from ``finance_agent.db``.

Conventions shared by every method:
- ``start`` is inclusive and ``end`` is exclusive, both dates passed in by the
  caller. Logic never reads the wall clock.
- Rows are bucketed by calendar month of ``posted_date``. A range that starts or
  ends mid-month yields partial first/last months.
- Pending transactions and internal transfers are excluded.
- ``currency`` filters to one currency, so amounts are never summed across
  currencies.
- Months with no activity are omitted, and an empty range returns empty ``rows``.
- Rows are ordered by ``month`` ascending, then ``category``.
- Every aggregate a chart shows (totals, shares, folded "other" buckets) is computed
  by the query, never by the chart layer, so it carries a ``result_id``.
- ``top_n`` keeps the N groups with the largest net spend over the whole range
  (ties broken by name, uncategorized last) and folds the rest into one row flagged
  ``is_other``. ``None`` keeps every group; ``top_n`` must be at least 1.
- ``spend`` is ``-SUM(amount)`` over non-income categories, so refunds net against
  it; ``income`` is ``SUM(amount)`` over income categories; ``net = income - spend``.
"""

from datetime import date
from typing import Literal, Protocol

from finance_agent.queries.result import (
    CashFlowRow,
    MonthlyCategorySpendRow,
    QueryResult,
    ScalarRow,
    SpendBreakdownRow,
)

KpiMeasure = Literal["spend", "income", "net"]
BreakdownGroupBy = Literal["category"]  # merchant and account arrive with their own queries


class SeriesCatalog(Protocol):
    def monthly_spend_by_category(
        self, start: date, end: date, currency: str, top_n: int | None = None
    ) -> QueryResult[MonthlyCategorySpendRow]:
        """Spend per category per month (stacked bars, trend lines).

        With ``top_n``, categories outside the top N over the range are folded, per
        month, into one row with ``is_other`` set.
        """
        ...

    def cash_flow(self, start: date, end: date, currency: str) -> QueryResult[CashFlowRow]:
        """Inflow, outflow and net per month (cash flow bars)."""
        ...

    def spend_breakdown(
        self,
        start: date,
        end: date,
        currency: str,
        group_by: BreakdownGroupBy = "category",
        top_n: int | None = None,
    ) -> QueryResult[SpendBreakdownRow]:
        """Spend per group over the whole range with each group's share of the total.

        Rows are ordered by ``amount`` descending, then group name (uncategorized last,
        the ``is_other`` bucket always last). ``totals`` holds ``{"spend": total}``.
        """
        ...

    def kpi(
        self,
        measure: KpiMeasure,
        start: date,
        end: date,
        currency: str,
        category: str | None = None,
    ) -> QueryResult[ScalarRow]:
        """One number for the range (stat tiles), returned in ``value``.

        ``category`` narrows ``spend`` to one category and is rejected with
        ``ValueError`` for ``income`` and ``net``. A range with no activity yields a
        ``value`` of zero: unlike ``rows``, a scalar has no "no data" form.
        """
        ...
