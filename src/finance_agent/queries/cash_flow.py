"""``net_cash_flow``: what came in, what went out, and the difference, for a date range.

A scalar query: it sets ``value`` (the net) and ``totals`` and carries no rows, so its
type is ``QueryResult[ScalarRow]``. ``CashFlowRow`` is the *monthly* row type for
``SeriesCatalog.cash_flow``.

The minimal flow query. It counts only posted rows that are not internal transfers, in
accounts whose role counts toward cash flow (``on_budget`` and ``credit``; not ``loan``
or ``investment``), in one currency. Closed accounts still count: ``closed`` only
affects account lists and forecasts. Inflow is the sum of positive amounts and outflow
the absolute sum of negative ones, so a refund counts as inflow here (category-level
spend nets refunds instead; see ``spend_by_category``).
"""

import uuid
from datetime import date
from decimal import Decimal

from finance_agent.db.loader import Connection
from finance_agent.queries.meta import data_stamp
from finance_agent.queries.result import QueryResult, ScalarRow

AMOUNTS_IN = (
    "Decimal amounts as strings, in the currency named in params. inflow and outflow are "
    "positive magnitudes; net = inflow - outflow and can be negative. Internal transfers "
    "are excluded."
)


def net_cash_flow(
    conn: Connection, tenant_id: str, start: date, end: date, currency: str
) -> QueryResult[ScalarRow]:
    """Net cash flow for ``start`` (inclusive) to ``end`` (exclusive) in ``currency``."""
    row = conn.execute(
        """
        SELECT COALESCE(SUM(t.amount) FILTER (WHERE t.amount > 0), 0),
               COALESCE(-SUM(t.amount) FILTER (WHERE t.amount < 0), 0)
        FROM transactions t
        JOIN accounts a ON a.tenant_id = t.tenant_id AND a.id = t.account_id
        WHERE t.tenant_id = %s
          AND NOT t.pending
          AND NOT t.is_internal_transfer
          AND a.role IN ('on_budget', 'credit')
          AND a.currency = %s
          AND a.currency_kind = 'iso'
          AND t.posted_date >= %s
          AND t.posted_date < %s
        """,
        (tenant_id, currency, start, end),
    ).fetchone()
    assert row is not None
    inflow, outflow = Decimal(row[0]), Decimal(row[1])
    data_version, as_of = data_stamp(conn, tenant_id)
    return QueryResult[ScalarRow](
        query="net_cash_flow",
        params={"start": start.isoformat(), "end": end.isoformat(), "currency": currency},
        result_id=uuid.uuid4().hex,
        data_version=data_version,
        as_of=as_of,
        amounts_in=AMOUNTS_IN,
        value=inflow - outflow,
        totals={"inflow": inflow, "outflow": outflow, "net": inflow - outflow},
    )
