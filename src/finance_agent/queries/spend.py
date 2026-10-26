from datetime import date
from decimal import Decimal

from finance_agent.db.loader import Connection


def spend_by_category(
    conn: Connection, tenant_id: str, reference_month: date, category: str, currency: str
) -> Decimal:
    """Net spend for ``category`` in the month containing ``reference_month``.

    spend = -SUM(amount) over posted (non-pending) transactions, so refunds net
    against purchases. Only accounts in ``currency`` count, and custom currencies
    (miles, points) never do, so amounts are never summed across currencies.
    Returns Decimal("0") when nothing matches.
    """
    start = reference_month.replace(day=1)
    end = date(start.year + start.month // 12, start.month % 12 + 1, 1)
    row = conn.execute(
        """
        SELECT COALESCE(-SUM(t.amount), 0)
        FROM transactions t
        JOIN accounts a ON a.tenant_id = t.tenant_id AND a.id = t.account_id
        WHERE t.tenant_id = %s
          AND t.category = %s
          AND NOT t.pending
          AND a.currency = %s
          AND a.currency_kind = 'iso'
          AND t.posted_date >= %s
          AND t.posted_date < %s
        """,
        (tenant_id, category, currency, start, end),
    ).fetchone()
    if row is None or not isinstance(row[0], Decimal):
        raise TypeError(f"expected a Decimal total, got {row!r}")
    return row[0]
