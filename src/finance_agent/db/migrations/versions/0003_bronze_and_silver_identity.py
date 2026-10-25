"""Bronze pulls and collision-proof silver identity.

- raw_payloads becomes raw_pulls: the exact bytes (BYTEA) plus request metadata.
- connections are new; accounts and transactions get surrogate ids, and an
  account is identified by (connection, external id) instead of just its id,
  because SimpleFIN account ids are only unique within a connection.
- posted_date may be NULL while a transaction is pending; transacted_date is new.
- accounts.org_name is gone: the institution name lives on connections.

Existing rows move under one 'legacy' connection per tenant. Legacy raw payloads
keep their JSONB text as the body: not the original bytes, which were never kept.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
            UNIQUE (tenant_id, body_sha256)
        )
        """
    )
    op.execute(
        """
        INSERT INTO raw_pulls (
            tenant_id, source, dialect_detected, fetched_at, body, body_sha256,
            body_json, parse_status
        )
        SELECT tenant_id, source, 'v1', loaded_at,
               convert_to(payload::text, 'UTF8'),
               encode(sha256(convert_to(payload::text, 'UTF8')), 'hex'),
               payload, 'ok'
        FROM raw_payloads
        ORDER BY id
        ON CONFLICT (tenant_id, body_sha256) DO NOTHING
        """
    )
    op.execute("DROP TABLE raw_payloads")

    op.execute("CREATE TEMP TABLE _legacy_accounts AS SELECT * FROM accounts")
    op.execute("CREATE TEMP TABLE _legacy_transactions AS SELECT * FROM transactions")
    op.execute("DROP TABLE transactions")
    op.execute("DROP TABLE accounts")

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
        CREATE TABLE accounts (
            tenant_id     TEXT    NOT NULL,
            id            BIGSERIAL,
            connection_id BIGINT  NOT NULL,
            external_id   TEXT    NOT NULL,
            name          TEXT    NOT NULL,
            currency      TEXT    NOT NULL,
            balance       NUMERIC NOT NULL,
            PRIMARY KEY (tenant_id, id),
            UNIQUE (tenant_id, connection_id, external_id),
            FOREIGN KEY (tenant_id, connection_id) REFERENCES connections (tenant_id, id)
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
        "CREATE INDEX transactions_transfer_group_idx "
        "ON transactions (tenant_id, transfer_group_id)"
    )

    op.execute(
        """
        INSERT INTO connections (tenant_id, source, provider_key, name, first_seen_at)
        SELECT t.tenant_id, 'simplefin', 'legacy', 'legacy',
               COALESCE(
                   (SELECT min(r.fetched_at) FROM raw_pulls r WHERE r.tenant_id = t.tenant_id),
                   now()
               )
        FROM (SELECT DISTINCT tenant_id FROM _legacy_accounts) t
        """
    )
    op.execute(
        """
        INSERT INTO accounts (tenant_id, connection_id, external_id, name, currency, balance)
        SELECT a.tenant_id, c.id, a.external_id, a.name, a.currency, a.balance
        FROM _legacy_accounts a
        JOIN connections c ON c.tenant_id = a.tenant_id AND c.provider_key = 'legacy'
        """
    )
    op.execute(
        """
        INSERT INTO transactions (
            tenant_id, account_id, external_id, posted_date, amount, description,
            category, pending, raw, transfer_group_id, is_internal_transfer, category_source
        )
        SELECT x.tenant_id, a.id, x.external_id, x.posted_date, x.amount, x.description,
               x.category, x.pending, x.raw, x.transfer_group_id, x.is_internal_transfer,
               x.category_source
        FROM _legacy_transactions x
        JOIN accounts a
          ON a.tenant_id = x.tenant_id AND a.external_id = x.account_external_id
        """
    )
    op.execute("DROP TABLE _legacy_accounts, _legacy_transactions")


def downgrade() -> None:
    """Back to the 0002 shape. Lossy by nature: accounts that share an external id
    across connections collapse to the first, pending rows without a posted date
    get their transacted date (or 1970-01-01), and pulls that were not JSON are dropped.
    """
    op.execute(
        """
        CREATE TEMP TABLE _new_accounts AS
        SELECT a.tenant_id, a.id, a.external_id, a.name, a.currency, a.balance,
               c.name AS org_name
        FROM accounts a
        JOIN connections c ON c.tenant_id = a.tenant_id AND c.id = a.connection_id
        """
    )
    op.execute(
        """
        CREATE TEMP TABLE _new_transactions AS
        SELECT t.*, a.external_id AS account_external_id
        FROM transactions t
        JOIN accounts a ON a.tenant_id = t.tenant_id AND a.id = t.account_id
        """
    )
    op.execute("CREATE TEMP TABLE _new_pulls AS SELECT * FROM raw_pulls")
    op.execute("DROP TABLE transactions, accounts, connections, raw_pulls")

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
            tenant_id            TEXT    NOT NULL,
            account_external_id  TEXT    NOT NULL,
            external_id          TEXT    NOT NULL,
            posted_date          DATE    NOT NULL,
            amount               NUMERIC NOT NULL,
            description          TEXT    NOT NULL,
            category             TEXT,
            pending              BOOLEAN NOT NULL,
            raw                  JSONB   NOT NULL DEFAULT '{}',
            transfer_group_id    BIGINT,
            is_internal_transfer BOOLEAN NOT NULL DEFAULT false,
            category_source      TEXT CHECK (category_source IN ('rule', 'model', 'user')),
            PRIMARY KEY (tenant_id, account_external_id, external_id),
            FOREIGN KEY (tenant_id, account_external_id)
                REFERENCES accounts (tenant_id, external_id),
            FOREIGN KEY (tenant_id, transfer_group_id)
                REFERENCES transfer_groups (tenant_id, id),
            CONSTRAINT transactions_category_fkey FOREIGN KEY (tenant_id, category)
                REFERENCES categories (tenant_id, name) ON UPDATE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX transactions_transfer_group_idx "
        "ON transactions (tenant_id, transfer_group_id)"
    )
    op.execute(
        """
        INSERT INTO raw_payloads (tenant_id, source, payload, payload_sha256, loaded_at)
        SELECT tenant_id, source, body_json, body_sha256, fetched_at
        FROM _new_pulls
        WHERE body_json IS NOT NULL
        ORDER BY id
        ON CONFLICT (tenant_id, payload_sha256) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO accounts (tenant_id, external_id, name, org_name, currency, balance)
        SELECT tenant_id, external_id, name, org_name, currency, balance
        FROM _new_accounts
        ORDER BY id
        ON CONFLICT (tenant_id, external_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO transactions (
            tenant_id, account_external_id, external_id, posted_date, amount, description,
            category, pending, raw, transfer_group_id, is_internal_transfer, category_source
        )
        SELECT tenant_id, account_external_id, external_id,
               COALESCE(posted_date, transacted_date, DATE '1970-01-01'), amount, description,
               category, pending, raw, transfer_group_id, is_internal_transfer, category_source
        FROM _new_transactions
        ORDER BY id
        ON CONFLICT (tenant_id, account_external_id, external_id) DO NOTHING
        """
    )
    op.execute("DROP TABLE _new_accounts, _new_transactions, _new_pulls")
