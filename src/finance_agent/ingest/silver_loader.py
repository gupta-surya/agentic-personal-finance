"""Silver loader: a ``NormalizedBatch`` becomes connections, accounts and transactions.

This module knows nothing about any source. Derived columns (category,
category_source, transfer_group_id, is_internal_transfer) are written on first
insert only, so a re-pull never overwrites a rule, model or user value; only
connector-owned fields refresh.
"""

from finance_agent.db.loader import Connection, TenantNotProvisionedError
from finance_agent.ingest.contract import NormalizedBatch


def load_batch(conn: Connection, tenant_id: str, raw_pull_id: int, batch: NormalizedBatch) -> None:
    """Upsert the batch in one database transaction.

    ``raw_pull_id`` identifies the bronze row the batch came from; its fetch time
    stamps newly seen connections.
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
        fetched_at = pull[0]

        connection_ids: dict[str, int] = {}
        for connection in batch.connections:
            row = conn.execute(
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
                RETURNING id
                """,
                (
                    tenant_id,
                    batch.source,
                    connection.provider_key,
                    connection.name,
                    connection.org_id,
                    connection.org_url,
                    connection.sfin_url,
                    fetched_at,
                ),
            ).fetchone()
            assert row is not None
            connection_ids[connection.provider_key] = row[0]

        account_ids: dict[tuple[str, str], int] = {}
        for account in batch.accounts:
            row = conn.execute(
                """
                INSERT INTO accounts (
                    tenant_id, connection_id, external_id, name, currency, balance
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, connection_id, external_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    currency = EXCLUDED.currency,
                    balance = EXCLUDED.balance
                RETURNING id
                """,
                (
                    tenant_id,
                    connection_ids[account.connection_key],
                    account.external_id,
                    account.name,
                    account.currency,
                    account.balance,
                ),
            ).fetchone()
            assert row is not None
            account_ids[(account.connection_key, account.external_id)] = row[0]

        for txn in batch.transactions:
            # A hint the tenant doesn't have is left uncategorized, never a reason to abort.
            category = txn.category_hint if txn.category_hint in known else None
            conn.execute(
                """
                INSERT INTO transactions (
                    tenant_id, account_id, external_id, posted_date, transacted_date,
                    amount, description, category, category_source, pending, raw
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (tenant_id, account_id, external_id) DO UPDATE SET
                    posted_date = EXCLUDED.posted_date,
                    transacted_date = EXCLUDED.transacted_date,
                    amount = EXCLUDED.amount,
                    description = EXCLUDED.description,
                    pending = EXCLUDED.pending,
                    raw = EXCLUDED.raw
                """,
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
                ),
            )
