"""Ledger writes. Every change goes through an existing action function (they mark the result as
user-decided, which re-syncs never overwrite); the only SQL here touches the user-owned columns
``note``, ``hidden`` and ``display_name``. Each call is one database transaction."""

from datetime import UTC, datetime
from typing import Literal

from finance_agent.categorize.actions import correct_categories, save_rule
from finance_agent.db.loader import Connection
from finance_agent.reconcile.actions import link_as_transfer, mark_not_transfer, set_account_role
from finance_agent.reconcile.match import reconcile

MAX_BULK = 500


def _require_rows(conn: Connection, tenant_id: str, ids: list[int]) -> None:
    found = conn.execute(
        "SELECT count(*) FROM transactions WHERE tenant_id = %s AND id = ANY(%s)", (tenant_id, ids)
    ).fetchone()
    if found is None or found[0] != len(set(ids)):
        raise LookupError("a transaction does not exist")


def _set_flags(
    conn: Connection,
    tenant_id: str,
    ids: list[int],
    note: str | None | Literal["unset"] = "unset",
    hidden: bool | None = None,
) -> None:
    sets: list[str] = []
    params: list[object] = []
    if note != "unset":
        sets.append("note = %s")
        params.append(note or None)  # an empty note clears it
    if hidden is not None:
        sets.append("hidden = %s")
        params.append(hidden)
    if sets:  # last_changed_at moves so data_version (and cached figures) notice
        conn.execute(
            f"UPDATE transactions SET {', '.join(sets)}, last_changed_at = %s "
            "WHERE tenant_id = %s AND id = ANY(%s)",
            (*params, datetime.now(UTC), tenant_id, ids),
        )


def edit_transaction(
    conn: Connection,
    tenant_id: str,
    txn_id: int,
    category: str | None = None,
    note: str | None | Literal["unset"] = "unset",
    hidden: bool | None = None,
) -> None:
    with conn.transaction():
        _require_rows(conn, tenant_id, [txn_id])
        if category is not None:
            correct_categories(conn, tenant_id, [txn_id], category)
        _set_flags(conn, tenant_id, [txn_id], note, hidden)


def bulk_edit(
    conn: Connection,
    tenant_id: str,
    ids: list[int],
    category: str | None = None,
    hidden: bool | None = None,
) -> int:
    ids = list(dict.fromkeys(ids))
    if not 0 < len(ids) <= MAX_BULK:
        raise ValueError(f"send between 1 and {MAX_BULK} ids")
    with conn.transaction():
        _require_rows(conn, tenant_id, ids)
        if category is not None:
            correct_categories(conn, tenant_id, ids, category)
        _set_flags(conn, tenant_id, ids, hidden=hidden)
    return len(ids)


def change_transfer(
    conn: Connection,
    tenant_id: str,
    txn_id: int,
    action: Literal["not_transfer", "link"],
    other_id: int | None,
) -> None:
    if action == "not_transfer":
        mark_not_transfer(conn, tenant_id, txn_id)
    elif other_id is None:
        raise ValueError("link needs other_id")
    else:
        link_as_transfer(conn, tenant_id, txn_id, other_id)


def edit_account(
    conn: Connection,
    tenant_id: str,
    account_id: int,
    role: str | None = None,
    display_name: str | None | Literal["unset"] = "unset",
    hidden: bool | None = None,
) -> None:
    with conn.transaction():
        if (
            conn.execute(
                "SELECT 1 FROM accounts WHERE tenant_id = %s AND id = %s", (tenant_id, account_id)
            ).fetchone()
            is None
        ):
            raise LookupError(f"no account {account_id}")
        if role is not None:
            set_account_role(conn, tenant_id, account_id, role)
            reconcile(conn, tenant_id)  # a role change can change which rows are transfers
        if display_name != "unset":
            conn.execute(
                "UPDATE accounts SET display_name = %s WHERE tenant_id = %s AND id = %s",
                ((display_name or "").strip() or None, tenant_id, account_id),
            )
        if hidden is not None:
            conn.execute(
                "UPDATE accounts SET hidden = %s WHERE tenant_id = %s AND id = %s",
                (hidden, tenant_id, account_id),
            )


__all__ = [
    "MAX_BULK",
    "bulk_edit",
    "change_transfer",
    "edit_account",
    "edit_transaction",
    "save_rule",
]
