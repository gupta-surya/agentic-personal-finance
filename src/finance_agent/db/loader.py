"""Idempotent loader: SimpleFIN body -> raw_payloads, accounts, transactions.

Amount sign convention (must match schema.sql and every query): debits (money
out) are negative, credits (money in) are positive, and spend = -SUM(amount).
SimpleFIN already uses this convention, so amounts are stored as-is.

Derived columns (category, category_source, transfer_group_id,
is_internal_transfer) are written on first insert only: re-loading must never
overwrite a rule, model, or user value. Only connector-owned fields refresh.

Categories are a foreign key target. A tenant with no categories at all is not
provisioned (``TenantNotProvisionedError``: call ``seed_default_categories``
first); a category value the tenant doesn't have is stored as NULL
(uncategorized) and the load continues.
"""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from importlib.resources import files

import psycopg
from alembic import command
from alembic.config import Config
from psycopg.rows import TupleRow
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from finance_agent.clients.simplefin import parse_payload

Connection = psycopg.Connection[TupleRow]


class TenantNotProvisionedError(RuntimeError):
    """The tenant has no categories; seed them before loading transactions."""


def apply_schema(conn: Connection) -> None:
    """Migrate the database behind ``conn`` to the latest Alembic revision.

    Alembic runs on ``conn`` itself (not a second connection), so every
    connection parameter (sslmode, options, service, ...) is preserved and there
    is no cross-connection lock wait. ``conn`` must be idle (no open
    transaction); it is switched to non-autocommit for the duration so the
    migration is atomic, then restored. The connection is left open.
    """
    if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        raise RuntimeError("apply_schema needs an idle connection (no open transaction)")
    config = Config()
    config.set_main_option("script_location", str(files("finance_agent.db").joinpath("migrations")))
    engine = create_engine("postgresql+psycopg://", creator=lambda: conn, poolclass=StaticPool)
    was_autocommit = conn.autocommit
    conn.autocommit = False
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        conn.autocommit = was_autocommit
        # No engine.dispose(): that would close the caller's connection.


def _dumps_exact(value: object) -> str:
    """JSON-encode ``value``, writing Decimal as the exact number text it was parsed from."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return "{" + ",".join(f"{json.dumps(k)}:{_dumps_exact(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_dumps_exact(v) for v in value) + "]"
    return json.dumps(value)


def load_payload(conn: Connection, tenant_id: str, body: str, source: str = "simplefin") -> None:
    """Store the raw body and upsert its accounts and transactions in one transaction.

    Re-loading the same body is a no-op on row counts: the raw payload dedupes on
    its hash, and accounts/transactions upsert on their natural keys.
    """
    payload = parse_payload(body)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    # Original per-transaction objects, parallel to payload.accounts[*].transactions,
    # so ``raw`` keeps fields the typed model ignores.
    # Parsed with Decimal so numbers keep their exact text (1.10 stays 1.10).
    raw_accounts = json.loads(body, parse_float=Decimal)["accounts"]

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
        conn.execute(
            """
            INSERT INTO raw_payloads (tenant_id, source, payload, payload_sha256)
            VALUES (%s, %s, %s::jsonb, %s)
            ON CONFLICT (tenant_id, payload_sha256) DO NOTHING
            """,
            (tenant_id, source, body, digest),
        )
        for account, raw_account in zip(payload.accounts, raw_accounts, strict=True):
            conn.execute(
                """
                INSERT INTO accounts (tenant_id, external_id, name, org_name, currency, balance)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, external_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    org_name = EXCLUDED.org_name,
                    currency = EXCLUDED.currency,
                    balance = EXCLUDED.balance
                """,
                (
                    tenant_id,
                    account.id,
                    account.name,
                    account.org.name,
                    account.currency,
                    account.balance,
                ),
            )
            for txn, raw_txn in zip(
                account.transactions, raw_account.get("transactions", []), strict=True
            ):
                # An unrecognized category is left uncategorized, never a reason to abort.
                category = txn.category if txn.category in known else None
                conn.execute(
                    """
                    INSERT INTO transactions (
                        tenant_id, account_external_id, external_id, posted_date,
                        amount, description, category, category_source, pending, raw
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (tenant_id, account_external_id, external_id) DO UPDATE SET
                        posted_date = EXCLUDED.posted_date,
                        amount = EXCLUDED.amount,
                        description = EXCLUDED.description,
                        pending = EXCLUDED.pending,
                        raw = EXCLUDED.raw
                    """,
                    (
                        tenant_id,
                        account.id,
                        txn.id,
                        datetime.fromtimestamp(txn.posted, tz=UTC).date(),
                        txn.amount,
                        txn.description,
                        category,
                        # The fixture's extra.category stands in for rules until
                        # categorization is implemented.
                        "rule" if category is not None else None,
                        txn.pending,
                        _dumps_exact(raw_txn),
                    ),
                )
