"""User decisions about transfers and account roles.

Every action marks what it touches as user-decided (``transfer_source = 'user'`` or
``role_source = 'user'``), which the engine and re-ingests never overwrite.
"""

from psycopg.types.json import Jsonb

from finance_agent.db.loader import Connection
from finance_agent.reconcile.match import dissolve_group

ROLES: tuple[str, ...] = ("on_budget", "credit", "loan", "investment")


def set_account_role(conn: Connection, tenant_id: str, account_id: int, role: str) -> None:
    """Set an account's role as a user decision. A re-ingest never moves it."""
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}, got {role!r}")
    row = conn.execute(
        "SELECT 1 FROM accounts WHERE tenant_id = %s AND id = %s", (tenant_id, account_id)
    ).fetchone()
    if row is None:
        raise LookupError(f"no account {account_id} for tenant {tenant_id!r}")
    conn.execute(
        """
        UPDATE accounts SET role = %s, role_source = 'user'
        WHERE tenant_id = %s AND id = %s AND (role, role_source) IS DISTINCT FROM (%s, 'user')
        """,
        (role, tenant_id, account_id, role),
    )


def _leg_group(conn: Connection, tenant_id: str, txn_id: int) -> int | None:
    row = conn.execute(
        "SELECT transfer_group_id FROM transactions WHERE tenant_id = %s AND id = %s",
        (tenant_id, txn_id),
    ).fetchone()
    if row is None:
        raise LookupError(f"no transaction {txn_id} for tenant {tenant_id!r}")
    return None if row[0] is None else int(row[0])


def mark_not_transfer(conn: Connection, tenant_id: str, txn_id: int) -> None:
    """The user says this is not a transfer. If it was half of a group, the group is
    dissolved and both legs are marked user-decided, so neither is re-matched."""
    with conn.transaction():
        group_id = _leg_group(conn, tenant_id, txn_id)
        leg_ids = [txn_id]
        if group_id is not None:
            rows = conn.execute(
                "SELECT id FROM transactions WHERE tenant_id = %s AND transfer_group_id = %s",
                (tenant_id, group_id),
            ).fetchall()
            leg_ids = [int(r[0]) for r in rows]
            dissolve_group(conn, tenant_id, group_id)
        conn.execute(
            """
            UPDATE transactions
            SET transfer_group_id = NULL, is_internal_transfer = false, transfer_source = 'user'
            WHERE tenant_id = %s AND id = ANY(%s)
              AND (transfer_group_id, is_internal_transfer, transfer_source)
                  IS DISTINCT FROM (NULL::bigint, false, 'user')
            """,
            (tenant_id, leg_ids),
        )


def link_as_transfer(conn: Connection, tenant_id: str, txn_a: int, txn_b: int) -> int:
    """The user says these two rows are the legs of one transfer. Returns the group id.

    The legs must be posted, in different accounts, in the same currency, with exactly
    opposite amounts. A leg already in a group leaves it (that group is dissolved).
    """
    if txn_a == txn_b:
        raise ValueError("a transfer needs two different transactions")
    with conn.transaction():
        rows = conn.execute(
            """
            SELECT t.id, t.account_id, a.currency, t.amount, t.posted_date, t.pending
            FROM transactions t
            JOIN accounts a ON a.tenant_id = t.tenant_id AND a.id = t.account_id
            WHERE t.tenant_id = %s AND t.id = ANY(%s)
            """,
            (tenant_id, [txn_a, txn_b]),
        ).fetchall()
        if len(rows) != 2:
            raise LookupError(f"transactions {txn_a} and {txn_b} are not both in this tenant")
        first, second = rows
        if first[1] == second[1]:
            raise ValueError("both legs are in the same account")
        if first[2] != second[2]:
            raise ValueError("the legs are in different currencies")
        if first[3] + second[3] != 0 or first[3] == 0:
            raise ValueError("the legs must have exactly opposite, non-zero amounts")
        if first[5] or second[5]:
            raise ValueError("a pending transaction cannot be linked yet")
        out_leg, in_leg = sorted(rows, key=lambda r: r[3])

        for txn_id in (txn_a, txn_b):
            existing = _leg_group(conn, tenant_id, txn_id)
            if existing is not None:
                dissolve_group(conn, tenant_id, existing)

        gap = abs((out_leg[4] - in_leg[4]).days)
        evidence = {
            "transaction_ids": [out_leg[0], in_leg[0]],
            "amount": format(abs(out_leg[3]), "f"),
            "gap_days": gap,
            "keyword": None,
            "linked_by": "user",
        }
        group = conn.execute(
            """
            INSERT INTO transfer_groups (
                tenant_id, rule, window_days, evidence, source, match_confidence
            )
            VALUES (%s, 'user_link', NULL, %s, 'user', 'high')
            RETURNING id
            """,
            (tenant_id, Jsonb(evidence)),
        ).fetchone()
        assert group is not None
        conn.execute(
            """
            UPDATE transactions
            SET transfer_group_id = %s, is_internal_transfer = true, transfer_source = 'user'
            WHERE tenant_id = %s AND id = ANY(%s)
            """,
            (group[0], tenant_id, [txn_a, txn_b]),
        )
        return int(group[0])


def confirm_transfer(conn: Connection, tenant_id: str, group_id: int) -> None:
    """The user confirms a match. The group becomes user-owned, so the engine never
    touches it again, and it leaves the low-confidence review list."""
    with conn.transaction():
        row = conn.execute(
            "SELECT 1 FROM transfer_groups WHERE tenant_id = %s AND id = %s",
            (tenant_id, group_id),
        ).fetchone()
        if row is None:
            raise LookupError(f"no transfer group {group_id} for tenant {tenant_id!r}")
        conn.execute(
            """
            UPDATE transfer_groups SET source = 'user', match_confidence = 'high'
            WHERE tenant_id = %s AND id = %s
              AND (source, match_confidence) IS DISTINCT FROM ('user', 'high')
            """,
            (tenant_id, group_id),
        )
        conn.execute(
            """
            UPDATE transactions SET transfer_source = 'user'
            WHERE tenant_id = %s AND transfer_group_id = %s
              AND transfer_source IS DISTINCT FROM 'user'
            """,
            (tenant_id, group_id),
        )
