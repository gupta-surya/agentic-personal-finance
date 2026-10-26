"""Categorization: a merchant key on transactions and trigram search on rules.

- transactions.merchant_normalized: the normalized merchant key, derived and recomputable;
  filled by the categorizer.
- pg_trgm: fuzzy merchant matching. The extension is created here, inside the migration,
  because the test reset drops the public schema (and the extension with it), so every
  upgrade must be able to recreate it. It ships with the postgres image.
- A trigram GIN index on merchant_rules.merchant_normalized.

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("ALTER TABLE transactions ADD COLUMN merchant_normalized TEXT")
    op.execute(
        "CREATE INDEX merchant_rules_merchant_trgm_idx "
        "ON merchant_rules USING gin (merchant_normalized gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX merchant_rules_merchant_trgm_idx")
    op.execute("ALTER TABLE transactions DROP COLUMN merchant_normalized")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
