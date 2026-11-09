"""Baseline schema.

The single migration for the project. It creates the current schema directly; the earlier
incremental migrations (0001-0007) were squashed into this one before first release, while
no database was deployed anywhere. From here on, schema changes are new migrations again.

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fuzzy merchant matching. Created inside the migration because the test reset drops
    # the public schema (and the extension with it); ships with the postgres image.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute(
        """
        CREATE TABLE connections (
            tenant_id     TEXT        NOT NULL,
            id            BIGSERIAL,
            source        TEXT        NOT NULL,
            provider_key  TEXT        NOT NULL,
            name          TEXT        NOT NULL,
            org_id        TEXT,
            org_url       TEXT,
            sfin_url      TEXT,
            first_seen_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (tenant_id, id),
            UNIQUE (tenant_id, source, provider_key)
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
            is_income  BOOLEAN     NOT NULL DEFAULT false,
            PRIMARY KEY (tenant_id, id),
            UNIQUE (tenant_id, name)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE transfer_groups (
            tenant_id        TEXT        NOT NULL,
            id               BIGSERIAL,
            rule             TEXT        NOT NULL,
            window_days      INTEGER,
            evidence         JSONB       NOT NULL DEFAULT '{}',
            source           TEXT        NOT NULL CHECK (source IN ('rule', 'user')),
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            match_confidence TEXT        NOT NULL CHECK (match_confidence IN ('high', 'low')),
            PRIMARY KEY (tenant_id, id)
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
        CREATE TABLE accounts (
            tenant_id         TEXT    NOT NULL,
            id                BIGSERIAL,
            connection_id     BIGINT  NOT NULL,
            external_id       TEXT    NOT NULL,
            name              TEXT    NOT NULL,
            currency          TEXT    NOT NULL,
            balance           NUMERIC NOT NULL,
            currency_kind     TEXT    NOT NULL CHECK (currency_kind IN ('iso', 'custom')),
            available_balance NUMERIC,
            balance_as_of     TIMESTAMPTZ,
            stale             BOOLEAN NOT NULL,
            role              TEXT    NOT NULL
                CHECK (role IN ('on_budget', 'credit', 'loan', 'investment')),
            role_source       TEXT    NOT NULL CHECK (role_source IN ('rule', 'user')),
            closed            BOOLEAN NOT NULL,
            PRIMARY KEY (tenant_id, id),
            UNIQUE (tenant_id, connection_id, external_id),
            FOREIGN KEY (tenant_id, connection_id) REFERENCES connections (tenant_id, id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE raw_pulls (
            id                BIGSERIAL PRIMARY KEY,
            tenant_id         TEXT        NOT NULL,
            source            TEXT        NOT NULL,
            dialect_detected  TEXT,
            requested_version TEXT,
            server_versions   JSONB,
            request_params    JSONB       NOT NULL DEFAULT '{}',
            http_status       INTEGER,
            fetched_at        TIMESTAMPTZ NOT NULL,
            body              BYTEA       NOT NULL,
            body_sha256       TEXT        NOT NULL,
            body_json         JSONB,
            parse_status      TEXT CHECK (parse_status IN ('ok', 'unrecognized', 'invalid')),
            parse_error       TEXT,
            UNIQUE (tenant_id, body_sha256),
            UNIQUE (tenant_id, id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE transactions (
            tenant_id            TEXT    NOT NULL,
            id                   BIGSERIAL,
            account_id           BIGINT  NOT NULL,
            external_id          TEXT    NOT NULL,
            posted_date          DATE,
            transacted_date      DATE,
            amount               NUMERIC NOT NULL,
            description          TEXT    NOT NULL,
            category             TEXT,
            pending              BOOLEAN NOT NULL,
            raw                  JSONB   NOT NULL DEFAULT '{}',
            transfer_group_id    BIGINT,
            is_internal_transfer BOOLEAN NOT NULL DEFAULT false,
            category_source      TEXT CHECK (category_source IN ('rule', 'model', 'user')),
            first_seen_at        TIMESTAMPTZ NOT NULL,
            last_changed_at      TIMESTAMPTZ NOT NULL,
            missing_since        TIMESTAMPTZ,
            transfer_source      TEXT CHECK (transfer_source IN ('rule', 'user')),
            merchant_normalized  TEXT,
            PRIMARY KEY (tenant_id, id),
            UNIQUE (tenant_id, account_id, external_id),
            CHECK (posted_date IS NOT NULL OR pending),
            FOREIGN KEY (tenant_id, account_id) REFERENCES accounts (tenant_id, id),
            FOREIGN KEY (tenant_id, transfer_group_id)
                REFERENCES transfer_groups (tenant_id, id),
            CONSTRAINT transactions_category_fkey FOREIGN KEY (tenant_id, category)
                REFERENCES categories (tenant_id, name) ON UPDATE CASCADE
        )
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

    op.execute(
        "CREATE INDEX transactions_transfer_group_idx "
        "ON transactions (tenant_id, transfer_group_id)"
    )
    op.execute(
        "CREATE INDEX merchant_rules_merchant_trgm_idx "
        "ON merchant_rules USING gin (merchant_normalized gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA public CASCADE")
    op.execute("CREATE SCHEMA public")
