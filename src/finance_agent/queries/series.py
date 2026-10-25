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
"""

from datetime import date
from typing import Protocol

from finance_agent.queries.result import CashFlowRow, MonthlyCategorySpendRow, QueryResult


class SeriesCatalog(Protocol):
    def monthly_spend_by_category(
        self, start: date, end: date, currency: str
    ) -> QueryResult[MonthlyCategorySpendRow]:
        """Spend per category per month (stacked bars, trend lines)."""
        ...

    def cash_flow(self, start: date, end: date, currency: str) -> QueryResult[CashFlowRow]:
        """Inflow, outflow and net per month (cash flow bars)."""
        ...
