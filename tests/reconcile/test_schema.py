"""Migration 0005: account role, income flag, transfer provenance, match confidence."""

from decimal import Decimal
from typing import Any, Literal

import pytest
from psycopg.errors import CheckViolation

from finance_agent.db.default_categories import DEFAULT_CATEGORIES, seed_default_categories
from finance_agent.db.loader import Connection
from finance_agent.ingest.contract import (
    NormalizedAccount,
    NormalizedBatch,
    NormalizedConnection,
    NormalizeResult,
    RawPull,
)
from finance_agent.ingest.pipeline import ingest
from tests.helpers import FETCHED_AT, UTC_TZ, alembic, ingest_file

TENANT = "demo-tenant"
Role = Literal["on_budget", "credit", "loan", "investment"]


def _pairs(conn: Connection, query: str) -> dict[str, Any]:
    """Two-column query -> dict."""
    return {row[0]: row[1] for row in conn.execute(query).fetchall()}


def _one(conn: Connection, query: str, *params: object) -> tuple[Any, ...]:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return tuple(row)


def test_new_accounts_default_to_on_budget_open_and_rule_sourced(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_demo.json")

    rows = conn.execute("SELECT DISTINCT role, role_source, closed FROM accounts").fetchall()

    assert rows == [("on_budget", "rule", False)]


def test_upgrade_backfills_existing_rows(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_demo.json")
    alembic("downgrade", "0004")
    group = _one(
        conn,
        "INSERT INTO transfer_groups (tenant_id, rule, source) VALUES (%s, 'old', 'rule') "
        "RETURNING id",
        TENANT,
    )[0]
    conn.execute(
        "UPDATE transactions SET transfer_group_id = %s, is_internal_transfer = true "
        "WHERE external_id = 'chk-txn-001'",
        (group,),
    )

    alembic("upgrade", "head")

    assert conn.execute("SELECT DISTINCT role, role_source, closed FROM accounts").fetchall() == [
        ("on_budget", "rule", False)
    ]
    expected = {name: name == "income" for _, name in DEFAULT_CATEGORIES}
    assert _pairs(conn, "SELECT name, is_income FROM categories") == expected
    assert _one(conn, "SELECT match_confidence FROM transfer_groups") == ("high",)
    states = _pairs(conn, "SELECT external_id, transfer_source FROM transactions")
    assert states.pop("chk-txn-001") == "rule"
    assert set(states.values()) == {None} and len(states) == 11


def test_seed_marks_only_income_as_income_and_never_flips_a_user_choice(conn: Connection) -> None:
    flags = _pairs(conn, "SELECT name, is_income FROM categories")
    assert [name for name, flag in flags.items() if flag] == ["income"]

    conn.execute("UPDATE categories SET is_income = true WHERE name = 'other'")
    conn.execute("UPDATE categories SET is_income = false WHERE name = 'income'")
    seed_default_categories(conn, TENANT)

    flags = _pairs(conn, "SELECT name, is_income FROM categories")
    assert [name for name, flag in flags.items() if flag] == ["other"]


def test_a_user_added_category_can_be_income(conn: Connection) -> None:
    conn.execute(
        "INSERT INTO categories (tenant_id, group_name, name, is_income) "
        "VALUES (%s, 'Work', 'side_gig', true)",
        (TENANT,),
    )

    assert _one(conn, "SELECT is_income FROM categories WHERE name = 'side_gig'") == (True,)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE accounts SET role = 'savings'",
        "UPDATE accounts SET role_source = 'model'",
        "UPDATE transactions SET transfer_source = 'model'",
        "INSERT INTO transfer_groups (tenant_id, rule, source, match_confidence) "
        "VALUES ('demo-tenant', 'r', 'rule', 'medium')",
    ],
)
def test_new_check_constraints_reject_unknown_values(conn: Connection, statement: str) -> None:
    ingest_file(conn, TENANT, "simplefin_demo.json")

    with pytest.raises(CheckViolation):
        conn.execute(statement)


def _hinted_ingest(conn: Connection, hint: Role | None, body: bytes) -> None:
    """Ingest one account through a made-up source that supplies a role hint."""
    account = NormalizedAccount(
        connection_key="k",
        external_id="acct",
        name="Hinted",
        currency="USD",
        currency_kind="iso",
        balance=Decimal("10.00"),
        role_hint=hint,
    )
    batch = NormalizedBatch(
        source="hinting",
        dialect="v1",
        connections=[NormalizedConnection(provider_key="k", name="Bank")],
        accounts=[account],
        transactions=[],
    )
    result = NormalizeResult(status="ok", batch=batch, dialect="v1")
    ingest(
        conn,
        TENANT,
        RawPull(source="hinting", body=body, fetched_at=FETCHED_AT),
        UTC_TZ,
        normalizers={"hinting": lambda pull, tz: result},
    )


def test_a_connector_role_hint_sets_the_role_on_first_insert_only(conn: Connection) -> None:
    _hinted_ingest(conn, "credit", b"1")
    assert _one(conn, "SELECT role, role_source FROM accounts") == ("credit", "rule")

    _hinted_ingest(conn, "investment", b"2")  # a later pull's hint does not move it

    assert _one(conn, "SELECT role, role_source FROM accounts") == ("credit", "rule")


def test_no_hint_means_on_budget(conn: Connection) -> None:
    _hinted_ingest(conn, None, b"1")

    assert _one(conn, "SELECT role, role_source FROM accounts") == ("on_budget", "rule")


def test_a_user_role_survives_a_hinted_repull(conn: Connection) -> None:
    _hinted_ingest(conn, "credit", b"1")
    conn.execute("UPDATE accounts SET role = 'loan', role_source = 'user'")

    _hinted_ingest(conn, "credit", b"2")

    assert _one(conn, "SELECT role, role_source FROM accounts") == ("loan", "user")


def test_a_negative_balance_or_a_card_like_name_does_not_change_the_role(
    conn: Connection,
) -> None:
    ingest_file(conn, TENANT, "simplefin_demo.json")  # "Demo Rewards Card", balance -612.37

    rows = conn.execute("SELECT name, balance, role FROM accounts ORDER BY name").fetchall()

    assert rows == [
        ("Demo Checking", Decimal("4210.55"), "on_budget"),
        ("Demo Rewards Card", Decimal("-612.37"), "on_budget"),
    ]


def test_backfill_keeps_a_users_groups_user_owned(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_demo.json")
    alembic("downgrade", "0004")
    for source, legs in (("user", ("chk-txn-002", "chk-txn-003")), ("rule", ("chk-txn-001",))):
        group = _one(
            conn,
            "INSERT INTO transfer_groups (tenant_id, rule, source) VALUES (%s, 'old', %s) "
            "RETURNING id",
            TENANT,
            source,
        )[0]
        conn.execute(
            "UPDATE transactions SET transfer_group_id = %s, is_internal_transfer = true "
            "WHERE external_id = ANY(%s)",
            (group, list(legs)),
        )

    alembic("upgrade", "head")

    states = _pairs(conn, "SELECT external_id, transfer_source FROM transactions")
    assert states["chk-txn-002"] == states["chk-txn-003"] == "user"
    assert states["chk-txn-001"] == "rule"
    assert [v for k, v in states.items() if not k.startswith("chk-txn-00")] == [None] * 9
