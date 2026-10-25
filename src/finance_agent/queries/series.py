"""Signatures for the series queries charts need. Types only: no implementations.

Shared conventions for every query here:
- ``start`` is inclusive and ``end`` is exclusive, both dates passed in by the
  caller. Logic never reads the wall clock.
- Rows are bucketed by calendar month of ``posted_date``. A range that starts or
  ends mid-month yields partial first/last months.
- Pending transactions and internal transfers are excluded.
- ``currency`` filters to one currency, so amounts are never summed across
  currencies.
- Months with no activity are omitted, and an empty range returns empty ``rows``.
- Rows are ordered by ``month`` ascending, then ``category``.
"""

from datetime import date
from typing import Protocol

from finance_agent.db.loader import Connection
from finance_agent.queries.result import CashFlowRow, MonthlyCategorySpendRow, QueryResult


class MonthlySpendByCategory(Protocol):
    """Spend per category per month over a date range (stacked bar, trend lines)."""

    def __call__(
        self, conn: Connection, tenant_id: str, start: date, end: date, currency: str
    ) -> QueryResult[MonthlyCategorySpendRow]: ...


class CashFlow(Protocol):
    """Inflow, outflow and net per month over a date range (cash flow bars)."""

    def __call__(
        self, conn: Connection, tenant_id: str, start: date, end: date, currency: str
    ) -> QueryResult[CashFlowRow]: ...
