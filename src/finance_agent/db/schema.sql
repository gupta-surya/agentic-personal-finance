-- Current-state reference schema. The EXECUTABLE source of truth is the Alembic
-- migrations in db/migrations/versions; tests/test_phase1_schema.py fails if this
-- file and the migrated schema drift apart. Change both together.
--
-- Amount sign convention (must match loader.py and every query):
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

CREATE TABLE raw_payloads (
    id             BIGSERIAL PRIMARY KEY,
    tenant_id      TEXT        NOT NULL,
    source         TEXT        NOT NULL,
    payload        JSONB       NOT NULL,
    payload_sha256 TEXT        NOT NULL,
    loaded_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, payload_sha256)
);

CREATE TABLE accounts (
    tenant_id   TEXT    NOT NULL,
    external_id TEXT    NOT NULL,
    name        TEXT    NOT NULL,
    org_name    TEXT,
    currency    TEXT    NOT NULL,
    balance     NUMERIC NOT NULL,
    PRIMARY KEY (tenant_id, external_id)
);

-- Reconciliation evidence: which legs, which rule, what window.
CREATE TABLE transfer_groups (
    tenant_id   TEXT        NOT NULL,
    id          BIGSERIAL,
    rule        TEXT        NOT NULL,
    window_days INTEGER,
    evidence    JSONB       NOT NULL DEFAULT '{}',
    source      TEXT        NOT NULL CHECK (source IN ('rule', 'user')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

-- User-owned: group -> name, tenant-scoped.
CREATE TABLE categories (
    tenant_id  TEXT        NOT NULL,
    id         BIGSERIAL,
    group_name TEXT        NOT NULL,
    name       TEXT        NOT NULL,
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

CREATE TABLE transactions (
    tenant_id             TEXT    NOT NULL,
    account_external_id   TEXT    NOT NULL,
    external_id           TEXT    NOT NULL,
    posted_date           DATE    NOT NULL,  -- UTC date of SimpleFIN `posted`
    amount                NUMERIC NOT NULL,  -- debits negative, credits positive
    description           TEXT    NOT NULL,
    category              TEXT,              -- must exist in this tenant's categories; NULL = uncategorized
    pending               BOOLEAN NOT NULL,
    raw                   JSONB   NOT NULL DEFAULT '{}',  -- original per-transaction object
    transfer_group_id     BIGINT,
    is_internal_transfer  BOOLEAN NOT NULL DEFAULT false,
    category_source       TEXT CHECK (category_source IN ('rule', 'model', 'user')),
    PRIMARY KEY (tenant_id, account_external_id, external_id),
    FOREIGN KEY (tenant_id, account_external_id)
        REFERENCES accounts (tenant_id, external_id),
    FOREIGN KEY (tenant_id, transfer_group_id)
        REFERENCES transfer_groups (tenant_id, id),
    CONSTRAINT transactions_category_fkey FOREIGN KEY (tenant_id, category)
        REFERENCES categories (tenant_id, name) ON UPDATE CASCADE
);

CREATE INDEX transactions_transfer_group_idx ON transactions (tenant_id, transfer_group_id);
