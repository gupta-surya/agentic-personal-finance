"""Baseline: raw_payloads, accounts, transactions.

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE raw_payloads (
            id             BIGSERIAL PRIMARY KEY,
            tenant_id      TEXT        NOT NULL,
            source         TEXT        NOT NULL,
            payload        JSONB       NOT NULL,
            payload_sha256 TEXT        NOT NULL,
            loaded_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, payload_sha256)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE accounts (
            tenant_id   TEXT    NOT NULL,
            external_id TEXT    NOT NULL,
            name        TEXT    NOT NULL,
            org_name    TEXT,
            currency    TEXT    NOT NULL,
            balance     NUMERIC NOT NULL,
            PRIMARY KEY (tenant_id, external_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE transactions (
            tenant_id           TEXT    NOT NULL,
            account_external_id TEXT    NOT NULL,
            external_id         TEXT    NOT NULL,
            posted_date         DATE    NOT NULL,
            amount              NUMERIC NOT NULL,
            description         TEXT    NOT NULL,
            category            TEXT,
            pending             BOOLEAN NOT NULL,
            PRIMARY KEY (tenant_id, account_external_id, external_id),
            FOREIGN KEY (tenant_id, account_external_id)
                REFERENCES accounts (tenant_id, external_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE transactions, accounts, raw_payloads")
