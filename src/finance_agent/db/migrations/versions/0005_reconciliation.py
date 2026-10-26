"""Reconciliation: account role, income flag, transfer provenance and match confidence.

- accounts: role (on_budget | credit | loan | investment) with its source, and closed.
  Existing accounts become on_budget / rule / open: the connector cannot tell a card
  from a checking account, so the user sets the role.
- categories.is_income: income is a flag, not a name. Existing 'income' rows get it.
- transactions.transfer_source: who decided the transfer state (rule | user);
  NULL = never decided. Rows already in a group count as rule-decided.
- transfer_groups.match_confidence: high (a description signal) or low (none).
  Existing groups are high.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE accounts
            ADD COLUMN role        TEXT    NOT NULL DEFAULT 'on_budget'
                CHECK (role IN ('on_budget', 'credit', 'loan', 'investment')),
            ADD COLUMN role_source TEXT    NOT NULL DEFAULT 'rule'
                CHECK (role_source IN ('rule', 'user')),
            ADD COLUMN closed      BOOLEAN NOT NULL DEFAULT false
        """
    )
    op.execute(
        """
        ALTER TABLE accounts
            ALTER COLUMN role DROP DEFAULT,
            ALTER COLUMN role_source DROP DEFAULT,
            ALTER COLUMN closed DROP DEFAULT
        """
    )

    op.execute("ALTER TABLE categories ADD COLUMN is_income BOOLEAN NOT NULL DEFAULT false")
    op.execute("UPDATE categories SET is_income = true WHERE name = 'income'")

    op.execute(
        """
        ALTER TABLE transactions
            ADD COLUMN transfer_source TEXT CHECK (transfer_source IN ('rule', 'user'))
        """
    )
    # Legs of a group inherit who made it, so a user's group is never re-matched.
    op.execute(
        """
        UPDATE transactions t
        SET transfer_source = CASE g.source WHEN 'user' THEN 'user' ELSE 'rule' END
        FROM transfer_groups g
        WHERE g.tenant_id = t.tenant_id AND g.id = t.transfer_group_id
        """
    )

    op.execute(
        """
        ALTER TABLE transfer_groups
            ADD COLUMN match_confidence TEXT NOT NULL DEFAULT 'high'
                CHECK (match_confidence IN ('high', 'low'))
        """
    )
    op.execute("ALTER TABLE transfer_groups ALTER COLUMN match_confidence DROP DEFAULT")


def downgrade() -> None:
    op.execute("ALTER TABLE transfer_groups DROP COLUMN match_confidence")
    op.execute("ALTER TABLE transactions DROP COLUMN transfer_source")
    op.execute("ALTER TABLE categories DROP COLUMN is_income")
    op.execute("ALTER TABLE accounts DROP COLUMN closed, DROP COLUMN role_source, DROP COLUMN role")
