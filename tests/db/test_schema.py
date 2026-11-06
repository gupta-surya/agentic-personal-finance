import json
import os
from decimal import Decimal
from importlib.resources import files

import psycopg
import pytest
from psycopg.errors import CheckViolation, UniqueViolation

from finance_agent.db.default_categories import DEFAULT_CATEGORIES, seed_default_categories
from finance_agent.db.loader import Connection, TenantNotProvisionedError, apply_schema
from finance_agent.ingest.pipeline import ingest
from tests.helpers import FIXTURES, UTC_TZ, ingest_file, pull_from_file, pull_from_text
from tests.helpers import alembic as _alembic

FIXTURE = FIXTURES / "simplefin_demo.json"
TENANT = "demo-tenant"

SchemaShape = tuple[list[tuple[object, ...]], list[tuple[object, ...]]]


def _load(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_demo.json")


def _ingest_text(conn: Connection, body: str) -> None:
    ingest(conn, TENANT, pull_from_text(body), UTC_TZ)


def _body(transactions: list[dict[str, object]] | None, **account: object) -> str:
    """A one-account SimpleFIN body; ``transactions=None`` omits the key entirely."""
    acct: dict[str, object] = {
        "org": {"domain": "x.example", "sfin-url": "https://sfin.x.example"},
        "id": "acct-x",
        "name": "X",
        "currency": "USD",
        "balance": "0.00",
        **account,
    }
    if transactions is not None:
        acct["transactions"] = transactions
    return json.dumps({"errors": [], "accounts": [acct]})


def _count(conn: Connection, query: str) -> int:
    row = conn.execute(query).fetchone()
    assert row is not None
    return int(row[0])


def _shape(conn: Connection, schema: str) -> SchemaShape:
    """Columns and constraints of ``schema``, normalized for comparison.

    Known blind spots (it compares sets of definitions, not layout): column order
    (ordinal_position), the names of unnamed constraints, sequence ownership, and
    anything outside tables/columns/constraints/indexes (comments, grants).
    """
    columns = conn.execute(
        """
        SELECT table_name, column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name <> 'alembic_version'
        ORDER BY table_name, column_name
        """,
        (schema,),
    ).fetchall()
    constraints = conn.execute(
        """
        SELECT cls.relname, con.contype, pg_get_constraintdef(con.oid)
        FROM pg_constraint con
        JOIN pg_class cls ON cls.oid = con.conrelid
        JOIN pg_namespace ns ON ns.oid = cls.relnamespace
        WHERE ns.nspname = %s AND cls.relname <> 'alembic_version'
        ORDER BY 1, 2, 3
        """,
        (schema,),
    ).fetchall()
    # Sequence defaults embed the schema name; strip it so schemas compare equal.
    columns = [(*row[:4], str(row[4]).replace(f"{schema}.", "")) for row in columns]
    indexes = conn.execute(
        "SELECT indexname, indexdef FROM pg_indexes "
        "WHERE schemaname = %s AND tablename <> 'alembic_version' ORDER BY 1",
        (schema,),
    ).fetchall()
    # Constraint/index definitions qualify names outside the search path.
    constraints += [(name, "i", definition) for name, definition in indexes]
    constraints = [(*row[:2], str(row[2]).replace(f"{schema}.", "")) for row in constraints]
    return columns, constraints


def test_schema_sql_matches_migrations(conn: Connection) -> None:
    schema_sql = files("finance_agent.db").joinpath("schema.sql").read_text(encoding="utf-8")
    conn.execute("DROP SCHEMA IF EXISTS reference CASCADE")
    conn.execute("CREATE SCHEMA reference")
    try:
        conn.execute("SET search_path TO reference, public")  # public holds pg_trgm
        conn.execute(schema_sql)
        conn.execute("SET search_path TO public")
        assert _shape(conn, "reference") == _shape(conn, "public")
    finally:
        conn.execute("SET search_path TO public")
        conn.execute("DROP SCHEMA reference CASCADE")


def test_downgrade_then_upgrade_round_trips(conn: Connection) -> None:
    before = _shape(conn, "public")
    _alembic("downgrade", "base")
    assert _shape(conn, "public") == ([], [])
    _alembic("upgrade", "head")

    assert _shape(conn, "public") == before


def test_custom_category_round_trips(conn: Connection) -> None:
    seed_default_categories(conn, TENANT)
    conn.execute(
        "INSERT INTO categories (tenant_id, group_name, name) VALUES (%s, %s, %s)",
        (TENANT, "Pets", "vet"),
    )

    row = conn.execute(
        "SELECT group_name, name FROM categories WHERE tenant_id = %s AND name = %s",
        (TENANT, "vet"),
    ).fetchone()
    assert row == ("Pets", "vet")

    with pytest.raises(UniqueViolation):
        conn.execute(
            "INSERT INTO categories (tenant_id, group_name, name) VALUES (%s, %s, %s)",
            (TENANT, "Pets", "vet"),
        )
    # Names are unique per tenant, not globally.
    conn.execute(
        "INSERT INTO categories (tenant_id, group_name, name) VALUES (%s, %s, %s)",
        ("other-tenant", "Pets", "vet"),
    )


def test_seed_is_idempotent_and_small(conn: Connection) -> None:
    seed_default_categories(conn, TENANT)
    seed_default_categories(conn, TENANT)

    assert _count(conn, "SELECT count(*) FROM categories") == len(DEFAULT_CATEGORIES)
    assert len(DEFAULT_CATEGORIES) == 16
    names = {name for _, name in DEFAULT_CATEGORIES}
    assert {"income", "rent", "groceries", "dining", "subscriptions"} <= names


def test_seed_does_not_overwrite_user_edits(conn: Connection) -> None:
    seed_default_categories(conn, TENANT)
    conn.execute(
        "UPDATE categories SET group_name = 'Mine' WHERE tenant_id = %s AND name = 'groceries'",
        (TENANT,),
    )
    seed_default_categories(conn, TENANT)

    row = conn.execute(
        "SELECT group_name FROM categories WHERE tenant_id = %s AND name = 'groceries'", (TENANT,)
    ).fetchone()
    assert row == ("Mine",)


def test_source_columns_reject_unknown_values(conn: Connection) -> None:
    with pytest.raises(CheckViolation):
        conn.execute(
            "INSERT INTO merchant_rules (tenant_id, merchant_normalized, category, source) "
            "VALUES ('t', 'm', 'c', 'guess')"
        )


def test_raw_is_the_original_transaction_object(conn: Connection) -> None:
    _load(conn)

    original = json.loads(FIXTURE.read_text(encoding="utf-8"))["accounts"][0]["transactions"][2]
    row = conn.execute(
        "SELECT raw FROM transactions WHERE tenant_id = %s AND external_id = %s",
        (TENANT, original["id"]),
    ).fetchone()
    assert row is not None
    assert row[0] == original


def test_reload_never_overwrites_user_category(conn: Connection) -> None:
    _load(conn)
    conn.execute(
        "UPDATE transactions SET category = 'dining', category_source = 'user' "
        "WHERE tenant_id = %s AND external_id = 'chk-txn-003'",
        (TENANT,),
    )
    _load(conn)

    row = conn.execute(
        "SELECT category, category_source FROM transactions "
        "WHERE tenant_id = %s AND external_id = 'chk-txn-003'",
        (TENANT,),
    ).fetchone()
    assert row == ("dining", "user")


def test_fixture_shim_category_is_recorded_as_rule(conn: Connection) -> None:
    _load(conn)

    rows = conn.execute("SELECT category IS NOT NULL, category_source FROM transactions").fetchall()
    assert len(rows) == 12
    assert all(row == (True, "rule") for row in rows)


def test_transfer_group_links_transactions(conn: Connection) -> None:
    _load(conn)
    group = conn.execute(
        "INSERT INTO transfer_groups (tenant_id, rule, source, match_confidence) "
        "VALUES (%s, 'test', 'rule', 'high') "
        "RETURNING id",
        (TENANT,),
    ).fetchone()
    assert group is not None
    conn.execute(
        "UPDATE transactions SET transfer_group_id = %s, is_internal_transfer = true "
        "WHERE tenant_id = %s AND external_id = 'chk-txn-001'",
        (group[0], TENANT),
    )

    assert _count(conn, "SELECT count(*) FROM transactions WHERE is_internal_transfer") == 1
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(
            "UPDATE transactions SET transfer_group_id = 999999 WHERE tenant_id = %s",
            (TENANT,),
        )


def test_unknown_category_on_transaction_is_rejected(conn: Connection) -> None:
    _load(conn)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(
            "UPDATE transactions SET category = 'invented' WHERE external_id = 'chk-txn-003'"
        )


def test_unprovisioned_tenant_raises_a_clear_error(conn: Connection) -> None:
    # The taxonomy is seeded for demo-tenant only.
    with pytest.raises(TenantNotProvisionedError, match="seed_default_categories"):
        ingest(conn, "unseeded-tenant", pull_from_file("simplefin_demo.json"), UTC_TZ)

    assert _count(conn, "SELECT count(*) FROM transactions") == 0
    # The bytes are kept in bronze, unprocessed, so the pull can be reprocessed later.
    row = conn.execute("SELECT parse_status FROM raw_pulls").fetchone()
    assert row == (None,)


def test_unknown_category_value_loads_as_uncategorized(conn: Connection) -> None:
    body = _body(
        [
            {
                "id": "t1",
                "posted": 1773081000,
                "amount": "-1.00",
                "description": "X",
                "extra": {"category": "invented"},
            },
            {
                "id": "t2",
                "posted": 1773081000,
                "amount": "-2.00",
                "description": "Y",
                "extra": {"category": "groceries"},
            },
        ]
    )
    _ingest_text(conn, body)

    rows = conn.execute(
        "SELECT external_id, category, category_source FROM transactions ORDER BY external_id"
    ).fetchall()
    assert rows == [("t1", None, None), ("t2", "groceries", "rule")]


def test_null_category_is_allowed(conn: Connection) -> None:
    _load(conn)
    conn.execute(
        "UPDATE transactions SET category = NULL, category_source = NULL "
        "WHERE external_id = 'chk-txn-003'"
    )

    assert _count(conn, "SELECT count(*) FROM transactions WHERE category IS NULL") >= 1


def test_unknown_category_on_merchant_rule_is_rejected(conn: Connection) -> None:
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(
            "INSERT INTO merchant_rules (tenant_id, merchant_normalized, category, source) "
            "VALUES (%s, 'm', 'invented', 'model')",
            (TENANT,),
        )


def test_renaming_a_category_cascades(conn: Connection) -> None:
    _load(conn)
    conn.execute(
        "UPDATE categories SET name = 'food_shopping' WHERE tenant_id = %s AND name = 'groceries'",
        (TENANT,),
    )

    # The fixture has 8 groceries rows (including one pending).
    assert _count(conn, "SELECT count(*) FROM transactions WHERE category = 'food_shopping'") == 8
    assert _count(conn, "SELECT count(*) FROM transactions WHERE category = 'groceries'") == 0


def test_deleting_a_category_in_use_is_refused(conn: Connection) -> None:
    _load(conn)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(
            "DELETE FROM categories WHERE tenant_id = %s AND name = 'groceries'", (TENANT,)
        )


def test_numeric_amount_and_raw_keep_exact_number_text(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_numeric_amount.json")

    row = conn.execute(
        "SELECT amount, raw::text, raw -> 'extra' ->> 'fee' FROM transactions "
        "WHERE external_id = 'num-txn-001'"
    ).fetchone()
    assert row is not None
    assert row[0] == Decimal("-5.10")
    assert row[1].count("-5.10") == 1  # exact text, not -5.1
    assert row[2] == "1.10"


def test_reload_leaves_transfer_columns_untouched(conn: Connection) -> None:
    _load(conn)
    group = conn.execute(
        "INSERT INTO transfer_groups (tenant_id, rule, source, match_confidence) "
        "VALUES (%s, 't', 'user', 'high') "
        "RETURNING id",
        (TENANT,),
    ).fetchone()
    assert group is not None
    conn.execute(
        "UPDATE transactions SET transfer_group_id = %s, is_internal_transfer = true "
        "WHERE external_id = 'chk-txn-001'",
        (group[0],),
    )
    _load(conn)

    row = conn.execute(
        "SELECT transfer_group_id, is_internal_transfer FROM transactions "
        "WHERE external_id = 'chk-txn-001'"
    ).fetchone()
    assert row == (group[0], True)


def test_reload_refreshes_connector_owned_raw(conn: Connection) -> None:
    _load(conn)
    conn.execute("UPDATE transactions SET raw = '{}', description = 'stale'")
    _load(conn)

    row = conn.execute(
        "SELECT raw ->> 'description', description FROM transactions "
        "WHERE external_id = 'chk-txn-003'"
    ).fetchone()
    assert row == ("CORNER MARKET 0042", "CORNER MARKET 0042")


@pytest.mark.parametrize("source", ["rule", "model", "user"])
def test_reload_preserves_every_category_source(conn: Connection, source: str) -> None:
    _load(conn)
    conn.execute(
        "UPDATE transactions SET category = 'dining', category_source = %s "
        "WHERE external_id = 'chk-txn-003'",
        (source,),
    )
    _load(conn)

    row = conn.execute(
        "SELECT category, category_source FROM transactions WHERE external_id = 'chk-txn-003'"
    ).fetchone()
    assert row == ("dining", source)


def test_other_source_checks_reject_unknown_values(conn: Connection) -> None:
    _load(conn)
    with pytest.raises(CheckViolation):
        conn.execute("UPDATE transactions SET category_source = 'guess'")
    with pytest.raises(CheckViolation):
        conn.execute(
            "INSERT INTO transfer_groups (tenant_id, rule, source, match_confidence) "
            "VALUES (%s, 'r', 'model', 'high')",
            (TENANT,),
        )


def test_renaming_a_category_cascades_to_merchant_rules(conn: Connection) -> None:
    conn.execute(
        "INSERT INTO merchant_rules (tenant_id, merchant_normalized, category, source) "
        "VALUES (%s, 'corner market', 'groceries', 'user')",
        (TENANT,),
    )
    conn.execute(
        "UPDATE categories SET name = 'food_shopping' WHERE tenant_id = %s AND name = 'groceries'",
        (TENANT,),
    )

    row = conn.execute("SELECT category FROM merchant_rules").fetchone()
    assert row == ("food_shopping",)


@pytest.mark.parametrize(
    "transactions", [None, []], ids=["no-transactions-key", "empty-transactions"]
)
def test_account_without_transactions_loads(
    conn: Connection, transactions: list[dict[str, object]] | None
) -> None:
    _ingest_text(conn, _body(transactions))

    assert _count(conn, "SELECT count(*) FROM accounts") == 1
    assert _count(conn, "SELECT count(*) FROM transactions") == 0


def test_payload_with_errors_still_loads(conn: Connection) -> None:
    body = json.dumps(
        {
            "errors": ["Connection to Demo Bank may need attention"],
            "accounts": json.loads(_body([]))["accounts"],
        }
    )
    _ingest_text(conn, body)

    assert _count(conn, "SELECT count(*) FROM accounts") == 1


def test_upgrade_backfills_task01_data(conn: Connection) -> None:
    _alembic("downgrade", "base")
    _alembic("upgrade", "0001")
    conn.execute(
        "INSERT INTO accounts VALUES ('legacy', 'a1', 'A', NULL, 'USD', 0)",
    )
    conn.execute(
        "INSERT INTO transactions (tenant_id, account_external_id, external_id, posted_date, "
        "amount, description, category, pending) VALUES "
        "('legacy', 'a1', 't1', '2026-03-01', -1, 'x', 'groceries', false), "
        "('legacy', 'a1', 't2', '2026-03-01', -1, 'y', NULL, false)"
    )
    _alembic("upgrade", "head")

    cats = conn.execute("SELECT group_name, name FROM categories WHERE tenant_id = 'legacy'")
    assert cats.fetchall() == [("Other", "groceries")]
    rows = conn.execute(
        "SELECT external_id, category, category_source FROM transactions "
        "WHERE tenant_id = 'legacy' ORDER BY external_id"
    ).fetchall()
    assert rows == [("t1", "groceries", "rule"), ("t2", None, None)]


def test_apply_schema_works_on_a_non_autocommit_connection(conn: Connection) -> None:
    url = os.environ.get(
        "TEST_DATABASE_URL", "postgresql://finance:finance@127.0.0.1:5432/finance_test"
    )
    with psycopg.connect(url) as plain:  # autocommit off
        apply_schema(plain)  # already at head: must be a no-op, not a deadlock
        assert plain.autocommit is False
        assert plain.info.transaction_status == psycopg.pq.TransactionStatus.IDLE


def test_upgrade_moves_phase1_data_under_a_legacy_connection(conn: Connection) -> None:
    _alembic("downgrade", "base")
    _alembic("upgrade", "0002")
    conn.execute("INSERT INTO categories (tenant_id, group_name, name) VALUES ('t', 'Food', 'x')")
    conn.execute(
        "INSERT INTO raw_payloads (tenant_id, source, payload, payload_sha256) "
        "VALUES ('t', 'simplefin', '{\"accounts\": []}', 'old-hash')"
    )
    conn.execute("INSERT INTO accounts VALUES ('t', 'a1', 'Checking', 'Demo Bank', 'USD', 5)")
    conn.execute(
        "INSERT INTO transactions (tenant_id, account_external_id, external_id, posted_date, "
        "amount, description, category, pending, category_source) "
        "VALUES ('t', 'a1', 't1', '2026-03-01', -1.50, 'coffee', 'x', false, 'user')"
    )
    _alembic("upgrade", "head")

    assert conn.execute("SELECT source, provider_key, name FROM connections").fetchall() == [
        ("simplefin", "legacy", "legacy")
    ]
    assert conn.execute(
        "SELECT a.external_id, c.provider_key, t.external_id, t.amount, t.category, "
        "t.category_source, t.transacted_date "
        "FROM transactions t JOIN accounts a ON a.id = t.account_id "
        "JOIN connections c ON c.id = a.connection_id"
    ).fetchall() == [("a1", "legacy", "t1", Decimal("-1.50"), "x", "user", None)]
    pull = conn.execute(
        "SELECT dialect_detected, parse_status, convert_from(body, 'UTF8'), "
        "body_sha256 = encode(sha256(body), 'hex') FROM raw_pulls"
    ).fetchone()
    assert pull == ("v1", "ok", '{"accounts": []}', True)
    assert _count(conn, "SELECT count(*) FROM pg_tables WHERE tablename = 'raw_payloads'") == 0
