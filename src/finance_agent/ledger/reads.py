"""Row-level ledger reads over a read-only connection. Parameterized, tenant-scoped SQL; every
aggregate is computed in SQL and carries a ``result_id``. These rows go to the user's own
browser on loopback and never to a model."""

import base64
import json
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from finance_agent.db.loader import Connection
from finance_agent.ledger.models import (
    AccountGroup,
    AccountList,
    AccountPeriodSummary,
    AccountRef,
    AccountRow,
    AccountsSummary,
    BalancePoint,
    CardPayment,
    MerchantHistory,
    MonthAmount,
    OtherLeg,
    Sort,
    Status,
    TransactionDetail,
    TransactionPage,
    TransactionRow,
    TransactionTotals,
    TransferInfo,
)

UNCATEGORIZED = "__uncategorized__"
MAX_LIMIT = 200

_FROM = """
    FROM transactions t
    JOIN accounts a ON a.tenant_id = t.tenant_id AND a.id = t.account_id
    JOIN connections cn ON cn.tenant_id = a.tenant_id AND cn.id = a.connection_id
    LEFT JOIN categories c ON c.tenant_id = t.tenant_id AND c.name = t.category
    LEFT JOIN transfer_groups g ON g.tenant_id = t.tenant_id AND g.id = t.transfer_group_id
    LEFT JOIN transactions o ON o.tenant_id = t.tenant_id
        AND o.transfer_group_id = t.transfer_group_id AND o.id <> t.id
    LEFT JOIN accounts oa ON oa.tenant_id = o.tenant_id AND oa.id = o.account_id
"""
_NEEDS_REVIEW = "(t.category IS NULL AND NOT t.pending AND NOT t.is_internal_transfer)"
_SELECT = f"""
    SELECT t.id, t.posted_date, t.transacted_date, t.pending,
           COALESCE(NULLIF(t.merchant_normalized, ''), t.description), t.description,
           t.amount, a.currency, t.category, t.category_source, {_NEEDS_REVIEW}, t.note, t.hidden,
           a.id, COALESCE(a.display_name, a.name), a.role, cn.name,
           g.id, g.match_confidence,
           CASE WHEN a.role = 'credit' OR oa.role = 'credit' THEN 'card_payment'
                ELSE 'internal' END,
           o.id, COALESCE(oa.display_name, oa.name), o.posted_date
"""
# A transaction row that counts toward the catalog's figures (see TransactionTotals).
_COUNTED = (
    "NOT t.pending AND t.posted_date IS NOT NULL AND NOT t.is_internal_transfer AND NOT t.hidden "
    "AND a.role IN ('on_budget', 'credit') AND a.currency_kind = 'iso' "
    "AND a.currency = %(currency)s"
)


@dataclass
class TransactionFilters:
    start: date | None = None
    end: date | None = None  # exclusive
    account_ids: list[int] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    q: str | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    statuses: list[Status] = field(default_factory=list)
    include_transfers: bool = True
    currency: str = "USD"  # which currency the totals are in


def _where(tenant_id: str, f: TransactionFilters) -> tuple[str, dict[str, Any]]:
    p: dict[str, Any] = {"tenant": tenant_id, "currency": f.currency}
    parts = ["t.tenant_id = %(tenant)s"]
    when = "COALESCE(t.posted_date, t.transacted_date)"
    if f.start is not None:
        parts.append(f"{when} >= %(start)s")
        p["start"] = f.start
    if f.end is not None:
        parts.append(f"{when} < %(end)s")
        p["end"] = f.end
    if f.account_ids:
        parts.append("t.account_id = ANY(%(accounts)s)")
        p["accounts"] = f.account_ids
    if f.categories:
        names = [c for c in f.categories if c != UNCATEGORIZED]
        ors = ["t.category = ANY(%(categories)s)"]
        p["categories"] = names
        if UNCATEGORIZED in f.categories:
            ors.append("t.category IS NULL")
        parts.append("(" + " OR ".join(ors) + ")")
    if f.q:
        escaped = f.q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        p["q"] = f"%{escaped}%"
        parts.append(
            "(t.merchant_normalized ILIKE %(q)s OR t.description ILIKE %(q)s OR t.note ILIKE %(q)s)"
        )
    if f.min_amount is not None:
        parts.append("abs(t.amount) >= %(min_amount)s")
        p["min_amount"] = f.min_amount
    if f.max_amount is not None:
        parts.append("abs(t.amount) <= %(max_amount)s")
        p["max_amount"] = f.max_amount
    if not f.include_transfers:
        parts.append("NOT t.is_internal_transfer")
    status_sql = {
        "needs_review": _NEEDS_REVIEW,
        "pending": "t.pending",
        "transfer": "t.is_internal_transfer",
        "hidden": "t.hidden",
    }
    if f.statuses:
        parts.append("(" + " OR ".join(status_sql[s] for s in f.statuses) + ")")
    if "hidden" not in f.statuses:
        parts.append("NOT t.hidden")
    return " AND ".join(parts), p


# sort -> (key expression, direction, nulls clause)
_SORTS: dict[str, tuple[str, str, str]] = {
    "date_desc": ("t.posted_date", "DESC", " NULLS FIRST"),
    "date_asc": ("t.posted_date", "ASC", " NULLS LAST"),
    "amount_desc": ("abs(t.amount)", "DESC", ""),
    "amount_asc": ("abs(t.amount)", "ASC", ""),
}


def _encode_cursor(key: object, txn_id: int) -> str:
    raw = json.dumps([None if key is None else str(key), txn_id])
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[str | None, int]:
    try:
        key, txn_id = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return (None if key is None else str(key)), int(txn_id)
    except (ValueError, TypeError):
        raise ValueError("invalid cursor") from None


def _after(sort: str, cursor: str, p: dict[str, Any]) -> str:
    """The keyset predicate: rows strictly after the cursor row in this sort's order."""
    key, p["cid"] = _decode_cursor(cursor)
    expr, direction, _ = _SORTS[sort]
    cmp = "<" if direction == "DESC" else ">"
    if sort.startswith("amount"):
        p["ck"] = key
        return (
            f"({expr} {cmp} %(ck)s::numeric OR ({expr} = %(ck)s::numeric AND t.id {cmp} %(cid)s))"
        )
    if key is None:  # the cursor is on a pending row (no posted date)
        if direction == "DESC":  # NULLS FIRST: the rest of the nulls, then every dated row
            return f"(t.posted_date IS NULL AND t.id {cmp} %(cid)s OR t.posted_date IS NOT NULL)"
        return f"(t.posted_date IS NULL AND t.id {cmp} %(cid)s)"
    p["ck"] = key
    tail = " OR t.posted_date IS NULL" if direction == "ASC" else ""  # NULLS LAST
    return (
        f"(t.posted_date {cmp} %(ck)s::date "
        f"OR (t.posted_date = %(ck)s::date AND t.id {cmp} %(cid)s){tail})"
    )


def _row(r: tuple[Any, ...]) -> TransactionRow:
    transfer = None
    if r[17] is not None:
        other = OtherLeg(id=r[20], account_name=r[21], posted_date=r[22]) if r[20] else None
        transfer = TransferInfo(group_id=r[17], kind=r[19], confidence=r[18], other_leg=other)
    return TransactionRow(
        id=r[0],
        posted_date=r[1],
        transacted_date=r[2],
        pending=r[3],
        merchant=r[4],
        description=r[5],
        amount=r[6],
        currency=r[7],
        category=r[8],
        category_source=r[9],
        suggested_category=None,
        needs_review=r[10],
        note=r[11],
        hidden=r[12],
        account=AccountRef(id=r[13], name=r[14], mask=None, role=r[15], institution=r[16]),
        transfer=transfer,
    )


def list_transactions(
    conn: Connection,
    tenant_id: str,
    f: TransactionFilters,
    sort: Sort = "date_desc",
    limit: int = 100,
    cursor: str | None = None,
) -> TransactionPage:
    limit = max(1, min(limit, MAX_LIMIT))
    where, params = _where(tenant_id, f)
    page_params = dict(params, limit=limit + 1)
    page_where = where + (f" AND {_after(sort, cursor, page_params)}" if cursor else "")
    expr, direction, nulls = _SORTS[sort]
    rows = conn.execute(
        f"{_SELECT} {_FROM} WHERE {page_where} "
        f"ORDER BY {expr} {direction}{nulls}, t.id {direction} LIMIT %(limit)s",
        page_params,
    ).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if more:
        last = rows[-1]
        next_cursor = _encode_cursor(
            abs(last[6]) if sort.startswith("amount") else last[1], last[0]
        )
    # totals ignore paging: they describe the whole filtered window
    t = conn.execute(
        f"""
        SELECT count(*),
               COALESCE(-SUM(t.amount) FILTER (
                   WHERE {_COUNTED} AND NOT COALESCE(c.is_income, false)), 0),
               COALESCE(SUM(t.amount) FILTER (
                   WHERE {_COUNTED} AND COALESCE(c.is_income, false)), 0),
               count(*) FILTER (WHERE t.is_internal_transfer)
        FROM transactions t
        JOIN accounts a ON a.tenant_id = t.tenant_id AND a.id = t.account_id
        LEFT JOIN categories c ON c.tenant_id = t.tenant_id AND c.name = t.category
        WHERE {where}
        """,
        params,
    ).fetchone()
    assert t is not None
    return TransactionPage(
        rows=[_row(r) for r in rows],
        next_cursor=next_cursor,
        totals=TransactionTotals(
            count=t[0],
            money_out=t[1],
            money_in=t[2],
            transfers_excluded=t[3],
            currency=f.currency,
            result_id=uuid.uuid4().hex,
        ),
    )


def get_transaction(
    conn: Connection, tenant_id: str, txn_id: int, today: date
) -> TransactionDetail:
    row = conn.execute(
        f"{_SELECT} {_FROM} WHERE t.tenant_id = %s AND t.id = %s", (tenant_id, txn_id)
    ).fetchone()
    if row is None:
        raise LookupError(f"no transaction {txn_id}")
    key = conn.execute(
        "SELECT merchant_normalized FROM transactions WHERE tenant_id = %s AND id = %s",
        (tenant_id, txn_id),
    ).fetchone()
    history = None
    if key is not None and key[0]:
        months = conn.execute(
            """
            SELECT date_trunc('month', posted_date)::date, -SUM(amount), count(*)
            FROM transactions
            WHERE tenant_id = %s AND merchant_normalized = %s AND NOT pending AND NOT hidden
              AND NOT is_internal_transfer AND posted_date > %s AND posted_date <= %s
            GROUP BY 1 ORDER BY 1
            """,
            (tenant_id, key[0], today - timedelta(days=365), today),
        ).fetchall()
        history = MerchantHistory(
            visits_12m=sum(m[2] for m in months),
            total_12m=sum((m[1] for m in months), Decimal(0)),
            monthly=[MonthAmount(month=m[0], amount=m[1]) for m in months],
            result_id=uuid.uuid4().hex,
        )
    return TransactionDetail(transaction=_row(row), merchant_history=history)


_GROUP_LABELS = {
    "on_budget": "Cash",
    "credit": "Credit",
    "loan": "Loans",
    "investment": "Investments",
}


def list_accounts(
    conn: Connection, tenant_id: str, today: date, currency: str = "USD"
) -> AccountList:
    """Accounts grouped by role. Group totals and the summary are SQL sums over the visible
    (not hidden) ISO accounts in ``currency``: debts are negative balances, so ``credit_owed``
    is the negated credit sum, and loans and investments count only toward ``net_worth``."""
    month_start = today.replace(day=1)
    month_end = (month_start + timedelta(days=32)).replace(day=1)
    rows = conn.execute(
        """
        SELECT a.id, a.name, a.display_name, cn.name, a.role, a.role_source, a.currency,
               a.balance, a.available_balance, a.balance_as_of, a.stale, a.closed, a.hidden,
               (SELECT max(r.fetched_at) FROM raw_pulls r WHERE r.tenant_id = a.tenant_id
                  AND r.source = cn.source AND r.parse_status = 'ok'),
               cn.source,
               COALESCE((
                   SELECT -SUM(t.amount) FROM transactions t
                   LEFT JOIN categories c ON c.tenant_id = t.tenant_id AND c.name = t.category
                   WHERE t.tenant_id = a.tenant_id AND t.account_id = a.id
                     AND NOT t.pending AND NOT t.hidden AND NOT t.is_internal_transfer
                     AND NOT COALESCE(c.is_income, false)
                     AND t.posted_date >= %s AND t.posted_date < %s), 0)
        FROM accounts a
        JOIN connections cn ON cn.tenant_id = a.tenant_id AND cn.id = a.connection_id
        WHERE a.tenant_id = %s AND NOT a.hidden
        ORDER BY a.role, COALESCE(a.display_name, a.name), a.id
        """,
        (month_start, month_end, tenant_id),
    ).fetchall()
    sums: dict[str, Decimal] = dict(
        conn.execute(
            """
            SELECT role, SUM(balance) FROM accounts
            WHERE tenant_id = %s AND NOT hidden AND currency_kind = 'iso' AND currency = %s
            GROUP BY role
            """,
            (tenant_id, currency),
        ).fetchall()
    )
    summary = conn.execute(
        """
        SELECT COALESCE(SUM(balance) FILTER (WHERE role = 'on_budget'), 0),
               COALESCE(-SUM(balance) FILTER (WHERE role = 'credit'), 0),
               COALESCE(SUM(balance) FILTER (WHERE role IN ('on_budget', 'credit')), 0),
               COALESCE(SUM(balance), 0)
        FROM accounts
        WHERE tenant_id = %s AND NOT hidden AND currency_kind = 'iso' AND currency = %s
        """,
        (tenant_id, currency),
    ).fetchone()
    assert summary is not None
    by_role: dict[str, list[AccountRow]] = {}
    for r in rows:
        by_role.setdefault(r[4], []).append(
            AccountRow(
                id=r[0],
                name=r[1],
                display_name=r[2],
                mask=None,
                institution=r[3],
                role=r[4],
                role_source=r[5],
                currency=r[6],
                balance=r[7],
                available_balance=r[8],
                balance_as_of=r[9],
                stale=r[10],
                closed=r[11],
                hidden=r[12],
                last_sync_at=r[13],
                source=r[14],
                month_spend=r[15],
            )
        )
    groups = [
        AccountGroup(
            role=role,
            label=label,
            accounts=by_role[role],
            total=sums.get(role, Decimal(0)),
        )
        for role, label in _GROUP_LABELS.items()
        if role in by_role
    ]
    return AccountList(
        groups=groups,
        summary=AccountsSummary(
            cash=summary[0],
            credit_owed=summary[1],
            cash_after_cards=summary[2],
            net_worth=summary[3],
            currency=currency,
            result_id=uuid.uuid4().hex,
        ),
    )


def account_summary(
    conn: Connection, tenant_id: str, account_id: int, start: date, end: date
) -> AccountPeriodSummary:
    if (
        conn.execute(
            "SELECT 1 FROM accounts WHERE tenant_id = %s AND id = %s", (tenant_id, account_id)
        ).fetchone()
        is None
    ):
        raise LookupError(f"no account {account_id}")
    history = conn.execute(
        """
        SELECT as_of, balance FROM account_balances
        WHERE tenant_id = %s AND account_id = %s AND as_of::date >= %s AND as_of::date < %s
        ORDER BY as_of
        """,
        (tenant_id, account_id, start, end),
    ).fetchall()
    counts = conn.execute(
        f"""
        SELECT count(*), count(*) FILTER (WHERE {_NEEDS_REVIEW})
        FROM transactions t
        WHERE t.tenant_id = %s AND t.account_id = %s AND NOT t.hidden
          AND COALESCE(t.posted_date, t.transacted_date) >= %s
          AND COALESCE(t.posted_date, t.transacted_date) < %s
        """,
        (tenant_id, account_id, start, end),
    ).fetchone()
    assert counts is not None
    payment = conn.execute(
        """
        SELECT t.id, t.posted_date, t.amount, COALESCE(oa.display_name, oa.name)
        FROM transactions t
        JOIN accounts a ON a.tenant_id = t.tenant_id AND a.id = t.account_id
        JOIN transactions o ON o.tenant_id = t.tenant_id
            AND o.transfer_group_id = t.transfer_group_id AND o.id <> t.id
        JOIN accounts oa ON oa.tenant_id = o.tenant_id AND oa.id = o.account_id
        WHERE t.tenant_id = %s AND t.account_id = %s AND (a.role = 'credit' OR oa.role = 'credit')
        ORDER BY t.posted_date DESC NULLS FIRST, t.id DESC LIMIT 1
        """,
        (tenant_id, account_id),
    ).fetchone()
    return AccountPeriodSummary(
        account_id=account_id,
        start=start,
        end=end,
        balance_history=[BalancePoint(as_of=h[0], balance=h[1]) for h in history],
        transaction_count=counts[0],
        needs_review_count=counts[1],
        last_card_payment=None
        if payment is None
        else CardPayment(
            id=payment[0], posted_date=payment[1], amount=payment[2], other_account_name=payment[3]
        ),
        result_id=uuid.uuid4().hex,
    )
