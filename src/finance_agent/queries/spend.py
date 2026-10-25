from datetime import date
from decimal import Decimal

from finance_agent.db.loader import Connection


def spend_by_category(
    conn: Connection, tenant_id: str, reference_month: date, category: str
) -> Decimal:
    """Net spend for ``category`` in the month containing ``reference_month``.

    spend = -SUM(amount) over posted (non-pending) transactions, so refunds net
    against purchases. Returns Decimal("0") when nothing matches.
    """
    start = reference_month.replace(day=1)
    end = date(start.year + start.month // 12, start.month % 12 + 1, 1)
    row = conn.execute(
        """
        SELECT COALESCE(-SUM(amount), 0)
        FROM transactions
        WHERE tenant_id = %s
          AND category = %s
          AND NOT pending
          AND posted_date >= %s
          AND posted_date < %s
        """,
        (tenant_id, category, start, end),
    ).fetchone()
    if row is None or not isinstance(row[0], Decimal):
        raise TypeError(f"expected a Decimal total, got {row!r}")
    return row[0]
