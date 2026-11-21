"""Ledger columns (TASK-11): transaction notes and hiding, account display name and hiding,
the per-sync balance history, and the indexes the transaction list pages on.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE transactions ADD COLUMN note TEXT")
    op.execute("ALTER TABLE transactions ADD COLUMN hidden BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE accounts ADD COLUMN display_name TEXT")
    op.execute("ALTER TABLE accounts ADD COLUMN hidden BOOLEAN NOT NULL DEFAULT false")
    op.execute(
        """
        CREATE TABLE account_balances (
            tenant_id         TEXT        NOT NULL,
            account_id        BIGINT      NOT NULL,
            as_of             TIMESTAMPTZ NOT NULL,
            balance           NUMERIC     NOT NULL,
            available_balance NUMERIC,
            PRIMARY KEY (tenant_id, account_id, as_of),
            FOREIGN KEY (tenant_id, account_id) REFERENCES accounts (tenant_id, id)
        )
        """
    )
    # One row from the current balance, so history starts somewhere for existing data.
    op.execute(
        """
        INSERT INTO account_balances (tenant_id, account_id, as_of, balance, available_balance)
        SELECT tenant_id, id, COALESCE(balance_as_of, now()), balance, available_balance
        FROM accounts
        """
    )
    op.execute(
        "CREATE INDEX transactions_posted_idx "
        "ON transactions (tenant_id, posted_date DESC, id DESC)"
    )
    op.execute(
        "CREATE INDEX transactions_merchant_trgm_idx "
        "ON transactions USING gin (merchant_normalized gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE account_balances")
    op.execute("DROP INDEX transactions_merchant_trgm_idx")
    op.execute("DROP INDEX transactions_posted_idx")
    op.execute("ALTER TABLE accounts DROP COLUMN hidden, DROP COLUMN display_name")
    op.execute("ALTER TABLE transactions DROP COLUMN hidden, DROP COLUMN note")
