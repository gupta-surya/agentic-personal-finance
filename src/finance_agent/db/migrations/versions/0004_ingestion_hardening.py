"""Ingestion hardening: connector errors, balance freshness, pending tracking, currency kind.

- pull_errors: connector errors per pull; accounts.stale marks accounts they cover.
- accounts: available_balance, balance_as_of (so an older load can't win), stale,
  currency_kind (iso | custom; custom currencies are never fetched or summed).
- transactions: first_seen_at, last_changed_at, and missing_since (pending rows only).
  last_changed_at is when a pull last inserted or changed the row; an unchanged
  re-pull deliberately does not touch it, so it writes nothing.
- raw_pulls gets UNIQUE (tenant_id, id) so pull_errors can reference it per tenant.

Existing accounts get their currency kind from the currency text; existing
transactions take their connection's first-seen time.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE raw_pulls ADD UNIQUE (tenant_id, id)")

    op.execute(
        """
        ALTER TABLE accounts
            ADD COLUMN currency_kind     TEXT,
            ADD COLUMN available_balance NUMERIC,
            ADD COLUMN balance_as_of     TIMESTAMPTZ,
            ADD COLUMN stale             BOOLEAN NOT NULL DEFAULT false
        """
    )
    op.execute(
        """
        UPDATE accounts
        SET currency_kind = CASE WHEN currency ~* '^https?://' THEN 'custom' ELSE 'iso' END
        """
    )
    op.execute(
        """
        ALTER TABLE accounts
            ALTER COLUMN currency_kind SET NOT NULL,
            ALTER COLUMN stale DROP DEFAULT,
            ADD CHECK (currency_kind IN ('iso', 'custom'))
        """
    )

    op.execute(
        """
        ALTER TABLE transactions
            ADD COLUMN first_seen_at   TIMESTAMPTZ,
            ADD COLUMN last_changed_at TIMESTAMPTZ,
            ADD COLUMN missing_since   TIMESTAMPTZ
        """
    )
    op.execute(
        """
        UPDATE transactions t
        SET first_seen_at = c.first_seen_at, last_changed_at = c.first_seen_at
        FROM accounts a
        JOIN connections c ON c.tenant_id = a.tenant_id AND c.id = a.connection_id
        WHERE a.tenant_id = t.tenant_id AND a.id = t.account_id
        """
    )
    op.execute(
        """
        ALTER TABLE transactions
            ALTER COLUMN first_seen_at SET NOT NULL,
            ALTER COLUMN last_changed_at SET NOT NULL
        """
    )

    op.execute(
        """
        CREATE TABLE pull_errors (
            tenant_id     TEXT   NOT NULL,
            id            BIGSERIAL,
            raw_pull_id   BIGINT NOT NULL,
            code          TEXT   NOT NULL,
            message       TEXT   NOT NULL,
            connection_id BIGINT,
            account_id    BIGINT,
            PRIMARY KEY (tenant_id, id),
            FOREIGN KEY (tenant_id, raw_pull_id) REFERENCES raw_pulls (tenant_id, id),
            FOREIGN KEY (tenant_id, connection_id) REFERENCES connections (tenant_id, id),
            FOREIGN KEY (tenant_id, account_id) REFERENCES accounts (tenant_id, id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE pull_errors")
    op.execute(
        """
        ALTER TABLE transactions
            DROP COLUMN missing_since,
            DROP COLUMN last_changed_at,
            DROP COLUMN first_seen_at
        """
    )
    op.execute(
        """
        ALTER TABLE accounts
            DROP COLUMN stale,
            DROP COLUMN balance_as_of,
            DROP COLUMN available_balance,
            DROP COLUMN currency_kind
        """
    )
    op.execute("ALTER TABLE raw_pulls DROP CONSTRAINT raw_pulls_tenant_id_id_key")
