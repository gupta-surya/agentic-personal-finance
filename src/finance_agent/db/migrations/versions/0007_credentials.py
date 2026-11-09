"""Credentials zone: encrypted bank access URLs, isolated from connections and accounts.

A third zone beside bronze (raw bytes) and silver (data). tenant_id-scoped, ciphertext
only, with no foreign key into the data tables: the only path to it is the credentials
module, and a lookup is always tenant-scoped and returns nothing on miss (no global
fallback), so one tenant can never resolve another's bank access. ``key_id`` records which
key sealed the row so keys can rotate.

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE credentials (
            tenant_id  TEXT        NOT NULL,
            kind       TEXT        NOT NULL,
            ciphertext BYTEA       NOT NULL,
            key_id     TEXT        NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (tenant_id, kind)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE credentials")
