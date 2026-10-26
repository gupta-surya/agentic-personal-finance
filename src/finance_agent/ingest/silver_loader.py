"""Silver loader: a ``NormalizedBatch`` becomes connections, accounts and transactions.

This module knows nothing about any source. Rules that keep it safe to re-run:

- Derived columns (category, category_source, transfer_group_id,
  is_internal_transfer) are written on first insert only, so a re-pull never
  overwrites a rule, model or user value. Only connector-owned fields refresh.
- Every upsert is guarded with ``IS DISTINCT FROM``, so a pull that changes
  nothing writes nothing (no new row versions, no timestamps touched).
- Writes are batched (``executemany``), so round trips don't grow with row count.
- A balance only moves forward in ``balance_as_of``.
- Only PENDING rows are ever marked ``missing_since``; posted rows are never
  flagged or deleted.
"""

from collections.abc import Sequence
from datetime import datetime

from finance_agent.db.loader import Connection, TenantNotProvisionedError
from finance_agent.ingest.contract import NormalizedAccount, NormalizedBatch, PullError


def _covers(error: PullError, account: NormalizedAccount) -> bool:
    """Does this error apply to this account? Account-scoped, else connection-scoped."""
    if error.account_external_id is not None:
        return error.account_external_id == account.external_id and (
            error.connection_key in (None, account.connection_key)
        )
    return error.connection_key == account.connection_key


def load_batch(conn: Connection, tenant_id: str, raw_pull_id: int, batch: NormalizedBatch) -> None:
    """Upsert the batch in one database transaction.

    ``raw_pull_id`` identifies the bronze row the batch came from: its fetch time
    stamps what this pull saw, and connector errors are stored against it.
    """
    with conn.transaction():
        known = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM categories WHERE tenant_id = %s", (tenant_id,)
            ).fetchall()
        }
        if not known:
            raise TenantNotProvisionedError(
                f"tenant {tenant_id!r} has no categories; call seed_default_categories first"
            )
        pull = conn.execute(
            "SELECT fetched_at FROM raw_pulls WHERE tenant_id = %s AND id = %s",
            (tenant_id, raw_pull_id),
        ).fetchone()
        if pull is None:
            raise LookupError(f"no raw pull {raw_pull_id} for tenant {tenant_id!r}")
        fetched_at: datetime = pull[0]

        connection_ids = _upsert_connections(conn, tenant_id, batch, fetched_at)
        account_ids = _upsert_accounts(conn, tenant_id, batch, connection_ids)
        _record_errors(conn, tenant_id, raw_pull_id, batch, connection_ids)
        _upsert_transactions(conn, tenant_id, batch, account_ids, known, fetched_at)
        _flag_missing_pending(conn, tenant_id, batch, account_ids, fetched_at)


def _upsert_connections(
    conn: Connection, tenant_id: str, batch: NormalizedBatch, fetched_at: datetime
) -> dict[str, int]:
    if batch.connections:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO connections (
                    tenant_id, source, provider_key, name, org_id, org_url, sfin_url,
                    first_seen_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, source, provider_key) DO UPDATE SET
                    name = EXCLUDED.name,
                    org_id = EXCLUDED.org_id,
                    org_url = EXCLUDED.org_url,
                    sfin_url = EXCLUDED.sfin_url
                WHERE (connections.name, connections.org_id, connections.org_url,
                       connections.sfin_url)
                    IS DISTINCT FROM (EXCLUDED.name, EXCLUDED.org_id, EXCLUDED.org_url,
                                      EXCLUDED.sfin_url)
                """,
                [
                    (
                        tenant_id,
                        batch.source,
                        c.provider_key,
                        c.name,
                        c.org_id,
                        c.org_url,
                        c.sfin_url,
                        fetched_at,
                    )
                    for c in batch.connections
                ],
            )
    rows = conn.execute(
        "SELECT provider_key, id FROM connections "
        "WHERE tenant_id = %s AND source = %s AND provider_key = ANY(%s)",
        (tenant_id, batch.source, [c.provider_key for c in batch.connections]),
    ).fetchall()
    return {key: int(connection_id) for key, connection_id in rows}


def _upsert_accounts(
    conn: Connection, tenant_id: str, batch: NormalizedBatch, connection_ids: dict[str, int]
) -> dict[tuple[str, str], int]:
    if batch.accounts:
        # The balance triple applies only if this pull's balance is not older.
        newer = "accounts.balance_as_of IS NULL OR EXCLUDED.balance_as_of >= accounts.balance_as_of"
        with conn.cursor() as cur:
            cur.executemany(
                f"""
                INSERT INTO accounts (
                    tenant_id, connection_id, external_id, name, currency, currency_kind,
                    balance, available_balance, balance_as_of, stale,
                    role, role_source, closed
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'rule', false)
                ON CONFLICT (tenant_id, connection_id, external_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    currency = EXCLUDED.currency,
                    currency_kind = EXCLUDED.currency_kind,
                    stale = EXCLUDED.stale,
                    balance = CASE WHEN {newer} THEN EXCLUDED.balance
                                   ELSE accounts.balance END,
                    available_balance = CASE WHEN {newer} THEN EXCLUDED.available_balance
                                             ELSE accounts.available_balance END,
                    balance_as_of = CASE WHEN {newer} THEN EXCLUDED.balance_as_of
                                         ELSE accounts.balance_as_of END
                WHERE (accounts.name, accounts.currency, accounts.currency_kind, accounts.stale)
                        IS DISTINCT FROM (EXCLUDED.name, EXCLUDED.currency,
                                          EXCLUDED.currency_kind, EXCLUDED.stale)
                   OR (({newer}) AND (accounts.balance, accounts.available_balance,
                                      accounts.balance_as_of)
                        IS DISTINCT FROM (EXCLUDED.balance, EXCLUDED.available_balance,
                                          EXCLUDED.balance_as_of))
                """,
                [
                    (
                        tenant_id,
                        connection_ids[a.connection_key],
                        a.external_id,
                        a.name,
                        a.currency,
                        a.currency_kind,
                        a.balance,
                        a.available_balance,
                        a.balance_as_of,
                        any(_covers(e, a) for e in batch.errors),
                        # First insert only: a re-pull never overwrites a role the user set.
                        a.role_hint or "on_budget",
                    )
                    for a in batch.accounts
                ],
            )
    ids: dict[tuple[str, str], int] = {}
    by_connection = {connection_id: key for key, connection_id in connection_ids.items()}
    rows = conn.execute(
        "SELECT connection_id, external_id, id FROM accounts "
        "WHERE tenant_id = %s AND connection_id = ANY(%s)",
        (tenant_id, list(connection_ids.values())),
    ).fetchall()
    for connection_id, external_id, account_id in rows:
        ids[(by_connection[connection_id], external_id)] = int(account_id)
    return ids


def _record_errors(
    conn: Connection,
    tenant_id: str,
    raw_pull_id: int,
    batch: NormalizedBatch,
    connection_ids: dict[str, int],
) -> None:
    """Store each error against its pull, and mark every account it covers as stale.

    Accounts in this batch were already marked in the upsert. This also reaches
    accounts that are NOT in the batch, which is the usual case: a failing
    connection returns no accounts at all.
    """
    for error in batch.errors:
        connection_id = connection_ids.get(error.connection_key or "")
        if error.account_external_id is not None:
            scope = "AND connection_id = %s" if connection_id is not None else ""
            params: list[object] = [tenant_id, error.account_external_id]
            if connection_id is not None:
                params.append(connection_id)
            candidates = [
                int(row[0])
                for row in conn.execute(
                    f"SELECT id FROM accounts WHERE tenant_id = %s AND external_id = %s {scope}",
                    params,
                ).fetchall()
            ]
            # An id shared across connections is ambiguous: cover every candidate.
            targets: Sequence[int | None] = candidates or [None]
            conn.execute(
                "UPDATE accounts SET stale = true "
                "WHERE tenant_id = %s AND id = ANY(%s) AND NOT stale",
                (tenant_id, candidates),
            )
        else:
            targets = [None]
            if connection_id is not None:
                conn.execute(
                    "UPDATE accounts SET stale = true "
                    "WHERE tenant_id = %s AND connection_id = %s AND NOT stale",
                    (tenant_id, connection_id),
                )
        for account_id in targets:
            conn.execute(
                """
                INSERT INTO pull_errors (
                    tenant_id, raw_pull_id, code, message, connection_id, account_id
                )
                SELECT %s, %s, %s, %s, %s::bigint, %s::bigint
                WHERE NOT EXISTS (
                    SELECT 1 FROM pull_errors
                    WHERE tenant_id = %s AND raw_pull_id = %s AND code = %s AND message = %s
                      AND connection_id IS NOT DISTINCT FROM %s::bigint
                      AND account_id IS NOT DISTINCT FROM %s::bigint
                )
                """,
                (
                    tenant_id,
                    raw_pull_id,
                    error.code,
                    error.message,
                    connection_id,
                    account_id,
                    tenant_id,
                    raw_pull_id,
                    error.code,
                    error.message,
                    connection_id,
                    account_id,
                ),
            )


def _upsert_transactions(
    conn: Connection,
    tenant_id: str,
    batch: NormalizedBatch,
    account_ids: dict[tuple[str, str], int],
    known: set[str],
    fetched_at: datetime,
) -> None:
    if not batch.transactions:
        return
    rows = []
    for txn in batch.transactions:
        # A hint the tenant doesn't have is left uncategorized, never a reason to abort.
        category = txn.category_hint if txn.category_hint in known else None
        rows.append(
            (
                tenant_id,
                account_ids[(txn.connection_key, txn.account_external_id)],
                txn.external_id,
                txn.posted_date,
                txn.transacted_date,
                txn.amount,
                txn.description,
                category,
                # A source's own category hint stands in for rules until
                # categorization is implemented.
                "rule" if category is not None else None,
                txn.pending,
                txn.raw,
                fetched_at,
                fetched_at,
            )
        )
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO transactions (
                tenant_id, account_id, external_id, posted_date, transacted_date,
                amount, description, category, category_source, pending, raw,
                first_seen_at, last_changed_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            ON CONFLICT (tenant_id, account_id, external_id) DO UPDATE SET
                posted_date = EXCLUDED.posted_date,
                transacted_date = EXCLUDED.transacted_date,
                amount = EXCLUDED.amount,
                description = EXCLUDED.description,
                pending = EXCLUDED.pending,
                raw = EXCLUDED.raw,
                missing_since = NULL,
                last_changed_at = EXCLUDED.last_changed_at
            WHERE (transactions.posted_date, transactions.transacted_date, transactions.amount,
                   transactions.description, transactions.pending, transactions.raw,
                   transactions.missing_since)
                IS DISTINCT FROM (EXCLUDED.posted_date, EXCLUDED.transacted_date,
                                  EXCLUDED.amount, EXCLUDED.description, EXCLUDED.pending,
                                  EXCLUDED.raw, NULL::timestamptz)
            """,
            rows,
        )


def _flag_missing_pending(
    conn: Connection,
    tenant_id: str,
    batch: NormalizedBatch,
    account_ids: dict[tuple[str, str], int],
    fetched_at: datetime,
) -> None:
    """Mark pending rows the bank no longer returns. Posted rows are never touched.

    A pending row is flagged only when this pull asked for pending rows, no error
    covers its account, and the row is inside the requested window. A pending row
    with no transacted date can't be placed in a window, so a windowed pull never
    flags it. Date comparisons are strict: a row on the window's boundary date
    might be just outside the window, so it is left alone.
    """
    if not batch.pending_requested:
        return
    windowed = batch.window_start is not None or batch.window_end is not None
    for account in batch.accounts:
        if any(_covers(e, account) for e in batch.errors):
            continue
        seen = [
            t.external_id
            for t in batch.transactions
            if (t.connection_key, t.account_external_id)
            == (account.connection_key, account.external_id)
        ]
        conn.execute(
            """
            UPDATE transactions SET missing_since = %s
            WHERE tenant_id = %s AND account_id = %s
              AND pending AND missing_since IS NULL
              AND NOT (external_id = ANY(%s))
              AND (
                  NOT %s
                  OR (transacted_date IS NOT NULL
                      AND (%s::date IS NULL OR transacted_date > %s::date)
                      AND (%s::date IS NULL OR transacted_date < %s::date))
              )
            """,
            (
                fetched_at,
                tenant_id,
                account_ids[(account.connection_key, account.external_id)],
                seen,
                windowed,
                batch.window_start,
                batch.window_start,
                batch.window_end,
                batch.window_end,
            ),
        )
