-- Current-state reference schema. The EXECUTABLE source of truth is the Alembic
-- migrations in db/migrations/versions; tests/test_schema.py fails if this
-- file and the migrated schema drift apart. Change both together.
--
-- Amount sign convention (must match the normalizers, silver_loader.py and every query):
--   debits (money out) are negative, credits (money in) are positive,
--   and spend = -SUM(amount). Refunds are credits, so they net against spend.
--
-- Provenance: every derived field carries a source (rule | model | user), and a
-- pipeline re-run must never overwrite a user-set value. The loader therefore
-- writes derived columns (category, category_source, transfer_group_id,
-- is_internal_transfer) on first insert only.
--
-- Categories are referential: transactions.category and merchant_rules.category
-- must name a row in that tenant's categories (NULL stays allowed, so
-- confidence-gated "uncategorized" rows work). Renaming a category cascades;
-- deleting one that is in use is refused.
--
-- tenant_id is on every table.

-- Bronze: the exact bytes of every pull, written before anything is parsed.
-- parse_status NULL = received, not yet processed.
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
);

-- Silver. A connection is one login at one institution. Account ids are only
-- unique within a connection, so an account is (connection, external_id).
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
);

-- currency_kind 'custom' = a URL-identified currency (miles, points). It is stored
-- but never fetched, and never summed into money totals. stale = a connector error
-- covered this account in its latest pull. balance only moves forward in
-- balance_as_of, so loading an older pull can't regress it.
CREATE TABLE accounts (
    tenant_id         TEXT        NOT NULL,
    id                BIGSERIAL,
    connection_id     BIGINT      NOT NULL,
    external_id       TEXT        NOT NULL,
    name              TEXT        NOT NULL,
    currency          TEXT        NOT NULL,
    currency_kind     TEXT        NOT NULL CHECK (currency_kind IN ('iso', 'custom')),
    balance           NUMERIC     NOT NULL,
    available_balance NUMERIC,
    balance_as_of     TIMESTAMPTZ,
    stale             BOOLEAN     NOT NULL,
    -- role decides whether the account counts toward cash flow (on_budget and credit
    -- do; loan and investment don't). Never guessed from a balance sign or a name:
    -- a connector may hint it, otherwise on_budget, and the user changes it.
    role              TEXT        NOT NULL
        CHECK (role IN ('on_budget', 'credit', 'loan', 'investment')),
    role_source       TEXT        NOT NULL CHECK (role_source IN ('rule', 'user')),
    closed            BOOLEAN     NOT NULL,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, connection_id, external_id),
    FOREIGN KEY (tenant_id, connection_id) REFERENCES connections (tenant_id, id)
);

-- Connector errors, one row per error per pull. Store the message untouched;
-- sanitize it (ingest.sanitize.sanitize_for_display) before showing it.
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
);

-- Reconciliation evidence: which legs, which rule, what window.
CREATE TABLE transfer_groups (
    tenant_id   TEXT        NOT NULL,
    id          BIGSERIAL,
    rule        TEXT        NOT NULL,
    window_days INTEGER,
    evidence    JSONB       NOT NULL DEFAULT '{}',
    source      TEXT        NOT NULL CHECK (source IN ('rule', 'user')),
    -- low = matched on amount, window and accounts alone, with no transfer word in
    -- either description. Still treated as a transfer, but listed for confirmation.
    match_confidence TEXT   NOT NULL CHECK (match_confidence IN ('high', 'low')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

-- User-owned: group -> name, tenant-scoped.
CREATE TABLE categories (
    tenant_id  TEXT        NOT NULL,
    id         BIGSERIAL,
    group_name TEXT        NOT NULL,
    name       TEXT        NOT NULL,
    is_income  BOOLEAN     NOT NULL DEFAULT false,  -- income is a flag, never inferred from a name
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, name)
);

-- (tenant_id, merchant_normalized) -> category, with source.
CREATE TABLE merchant_rules (
    tenant_id           TEXT        NOT NULL,
    merchant_normalized TEXT        NOT NULL,
    category            TEXT        NOT NULL,
    source              TEXT        NOT NULL CHECK (source IN ('rule', 'model', 'user')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, merchant_normalized),
    CONSTRAINT merchant_rules_category_fkey FOREIGN KEY (tenant_id, category)
        REFERENCES categories (tenant_id, name) ON UPDATE CASCADE
);

-- Dates are the user's local calendar dates, not UTC. posted_date is NULL only
-- while a transaction is pending (SimpleFIN sends posted = 0 then).
CREATE TABLE transactions (
    tenant_id             TEXT    NOT NULL,
    id                    BIGSERIAL,
    account_id            BIGINT  NOT NULL,
    external_id           TEXT    NOT NULL,
    posted_date           DATE,
    transacted_date       DATE,
    amount                NUMERIC NOT NULL,  -- debits negative, credits positive
    description           TEXT    NOT NULL,
    category              TEXT,              -- must exist in this tenant's categories; NULL = uncategorized
    pending               BOOLEAN NOT NULL,
    raw                   JSONB   NOT NULL DEFAULT '{}',  -- original per-transaction object
    transfer_group_id     BIGINT,
    is_internal_transfer  BOOLEAN NOT NULL DEFAULT false,
    category_source       TEXT CHECK (category_source IN ('rule', 'model', 'user')),
    -- who decided the transfer state: rule (engine), user (linked or "not a transfer"),
    -- NULL = never decided. The engine only touches NULL and rule rows.
    transfer_source       TEXT CHECK (transfer_source IN ('rule', 'user')),
    -- first_seen_at: the pull that first inserted the row. last_changed_at: the
    -- last pull that inserted or changed it (an unchanged re-pull writes nothing).
    -- missing_since: set only on PENDING rows that a complete pull no longer returns.
    first_seen_at         TIMESTAMPTZ NOT NULL,
    last_changed_at       TIMESTAMPTZ NOT NULL,
    missing_since         TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, account_id, external_id),
    CHECK (posted_date IS NOT NULL OR pending),
    FOREIGN KEY (tenant_id, account_id) REFERENCES accounts (tenant_id, id),
    FOREIGN KEY (tenant_id, transfer_group_id) REFERENCES transfer_groups (tenant_id, id),
    CONSTRAINT transactions_category_fkey FOREIGN KEY (tenant_id, category)
        REFERENCES categories (tenant_id, name) ON UPDATE CASCADE
);

CREATE INDEX transactions_transfer_group_idx ON transactions (tenant_id, transfer_group_id);
