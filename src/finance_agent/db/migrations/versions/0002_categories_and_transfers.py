"""Category, reconciliation and rule tables.

Adds transfer_groups, categories, merchant_rules and the derived, correctable
columns on transactions (plus the per-transaction raw JSONB).

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE transfer_groups (
            tenant_id   TEXT        NOT NULL,
            id          BIGSERIAL,
            rule        TEXT        NOT NULL,
            window_days INTEGER,
            evidence    JSONB       NOT NULL DEFAULT '{}',
            source      TEXT        NOT NULL CHECK (source IN ('rule', 'user')),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE categories (
            tenant_id  TEXT        NOT NULL,
            id         BIGSERIAL,
            group_name TEXT        NOT NULL,
            name       TEXT        NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, id),
            UNIQUE (tenant_id, name)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE merchant_rules (
            tenant_id           TEXT        NOT NULL,
            merchant_normalized TEXT        NOT NULL,
            category            TEXT        NOT NULL,
            source              TEXT        NOT NULL CHECK (source IN ('rule', 'model', 'user')),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, merchant_normalized),
            CONSTRAINT merchant_rules_category_fkey FOREIGN KEY (tenant_id, category)
                REFERENCES categories (tenant_id, name) ON UPDATE CASCADE
        )
        """
    )
    op.execute(
        """
        ALTER TABLE transactions
            ADD COLUMN raw                  JSONB   NOT NULL DEFAULT '{}',
            ADD COLUMN transfer_group_id    BIGINT,
            ADD COLUMN is_internal_transfer BOOLEAN NOT NULL DEFAULT false,
            ADD COLUMN category_source      TEXT
                CHECK (category_source IN ('rule', 'model', 'user')),
            ADD FOREIGN KEY (tenant_id, transfer_group_id)
                REFERENCES transfer_groups (tenant_id, id)
        """
    )
    # Backfill existing rows so the category foreign key can be added:
    # every category already in use becomes a category row, and those values came
    # from the connector shim, which is recorded as source 'rule'. Their
    # per-transaction ``raw`` can't be recovered and stays '{}' until re-loaded.
    op.execute(
        """
        INSERT INTO categories (tenant_id, group_name, name)
        SELECT DISTINCT tenant_id, 'Other', category
        FROM transactions
        WHERE category IS NOT NULL
        """
    )
    op.execute("UPDATE transactions SET category_source = 'rule' WHERE category IS NOT NULL")
    op.execute(
        """
        ALTER TABLE transactions
            ADD CONSTRAINT transactions_category_fkey FOREIGN KEY (tenant_id, category)
                REFERENCES categories (tenant_id, name) ON UPDATE CASCADE
        """
    )
    op.execute(
        "CREATE INDEX transactions_transfer_group_idx "
        "ON transactions (tenant_id, transfer_group_id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE transactions DROP CONSTRAINT transactions_category_fkey")
    op.execute("DROP INDEX transactions_transfer_group_idx")
    op.execute(
        """
        ALTER TABLE transactions
            DROP COLUMN category_source,
            DROP COLUMN is_internal_transfer,
            DROP COLUMN transfer_group_id,
            DROP COLUMN raw
        """
    )
    op.execute("DROP TABLE merchant_rules, categories, transfer_groups")
