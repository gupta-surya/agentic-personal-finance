"""User decisions: link, un-link, confirm, roles; and the low-confidence review list."""

import json
from collections.abc import Callable
from datetime import UTC, date
from decimal import Decimal
from typing import Any

import pytest

from finance_agent.db.loader import Connection
from finance_agent.ingest.pipeline import ingest
from finance_agent.queries.meta import data_stamp
from finance_agent.reconcile.actions import (
    confirm_transfer,
    link_as_transfer,
    mark_not_transfer,
    set_account_role,
)
from finance_agent.reconcile.match import reconcile
from finance_agent.reconcile.review import list_low_confidence_matches
from tests.helpers import FIXTURES, UTC_TZ, ingest_file, pull_from_text

TENANT = "demo-tenant"


def _id(conn: Connection, external_id: str) -> int:
    row = conn.execute(
        "SELECT id FROM transactions WHERE external_id = %s", (external_id,)
    ).fetchone()
    assert row is not None
    return int(row[0])


def _account_id(conn: Connection, external_id: str) -> int:
    row = conn.execute("SELECT id FROM accounts WHERE external_id = %s", (external_id,)).fetchone()
    assert row is not None
    return int(row[0])


def _state(conn: Connection, *external_ids: str) -> list[tuple[Any, ...]]:
    return [
        tuple(
            conn.execute(
                "SELECT is_internal_transfer, transfer_group_id IS NOT NULL, transfer_source "
                "FROM transactions WHERE external_id = %s",
                (ext,),
            ).fetchone()
            or ()
        )
        for ext in external_ids
    ]


def _fixture_doc() -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(
        (FIXTURES / "simplefin_transfers.json").read_text(encoding="utf-8")
    )
    return doc


def _break(doc: dict[str, Any], txn_id: str, amount: str) -> dict[str, Any]:
    for account in doc["accounts"]:
        for txn in account["transactions"]:
            if txn["id"] == txn_id:
                txn["amount"] = amount
    return doc


# --- mark_not_transfer -----------------------------------------------------


def test_marking_an_unmatched_row_not_a_transfer_survives_a_rerun(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_transfers.json")

    mark_not_transfer(conn, TENANT, _id(conn, "t08"))
    result = reconcile(conn, TENANT)

    assert _state(conn, "t08", "s08") == [(False, False, "user"), (False, False, None)]
    assert result.matched == 5  # row 8's pair is not among them


def test_marking_one_leg_of_a_match_dissolves_it_and_sticks(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_transfers.json")
    reconcile(conn, TENANT)
    assert _state(conn, "t03", "s03") == [(True, True, "rule"), (True, True, "rule")]

    mark_not_transfer(conn, TENANT, _id(conn, "s03"))
    again = reconcile(conn, TENANT)

    assert _state(conn, "t03", "s03") == [(False, False, "user"), (False, False, "user")]
    assert again.matched == 0 and again.dissolved == 0
    count = conn.execute(
        "SELECT count(*) FROM transfer_groups g WHERE EXISTS (SELECT 1 FROM transactions t "
        "WHERE t.transfer_group_id = g.id AND t.external_id IN ('t03', 's03'))"
    ).fetchone()
    assert count == (0,)


def test_marking_is_idempotent(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_transfers.json")
    mark_not_transfer(conn, TENANT, _id(conn, "t07"))
    xmin = "SELECT xmin::text FROM transactions WHERE external_id = 't07'"
    before = conn.execute(xmin).fetchone()

    mark_not_transfer(conn, TENANT, _id(conn, "t07"))

    assert conn.execute(xmin).fetchone() == before


def test_marking_an_unknown_transaction_fails(conn: Connection) -> None:
    with pytest.raises(LookupError):
        mark_not_transfer(conn, TENANT, 999999)


# --- link_as_transfer ------------------------------------------------------


def test_a_user_link_survives_reruns_even_outside_the_window(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_transfers.json")  # t06 / s06 are 18 days apart

    group = link_as_transfer(conn, TENANT, _id(conn, "t06"), _id(conn, "s06"))
    reconcile(conn, TENANT)
    reconcile(conn, TENANT)

    assert _state(conn, "t06", "s06") == [(True, True, "user"), (True, True, "user")]
    row = conn.execute(
        "SELECT source, match_confidence, rule, window_days, evidence FROM transfer_groups "
        "WHERE id = %s",
        (group,),
    ).fetchone()
    assert row is not None
    assert row[:4] == ("user", "high", "user_link", None)
    assert row[4]["gap_days"] == 18 and row[4]["amount"] == "200.00"


def test_a_user_link_is_untouched_when_upstream_breaks_the_pair(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_transfers.json")
    link_as_transfer(conn, TENANT, _id(conn, "t03"), _id(conn, "s03"))

    doc = _break(_fixture_doc(), "s03", "1000.01")
    ingest(conn, TENANT, pull_from_text(json.dumps(doc)), UTC_TZ)
    result = reconcile(conn, TENANT)

    assert result.dissolved == 0
    assert _state(conn, "t03", "s03") == [(True, True, "user"), (True, True, "user")]


def test_linking_a_leg_that_is_already_matched_replaces_that_match(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_transfers.json")
    reconcile(conn, TENANT)  # t10a<->s10a (Mar 1) and t10b<->s10b (Mar 29)

    link_as_transfer(conn, TENANT, _id(conn, "t10a"), _id(conn, "s10b"))
    reconcile(conn, TENANT)

    # The user's pair holds; each old partner lost its match and is 28 days from the other.
    assert _state(conn, "t10a", "s10b") == [(True, True, "user"), (True, True, "user")]
    assert _state(conn, "s10a", "t10b") == [(False, False, None), (False, False, None)]


@pytest.mark.parametrize(
    ("a", "b", "message"),
    [
        ("t03", "t03", "two different"),
        ("t03", "c04", "opposite"),  # -1000 and +500
        ("t03", "s06", "opposite"),  # -1000 and +200
        ("t01", "t02", "same account"),
    ],
)
def test_linking_rejects_pairs_that_cannot_be_a_transfer(
    conn: Connection, a: str, b: str, message: str
) -> None:
    ingest_file(conn, TENANT, "simplefin_transfers.json")

    with pytest.raises(ValueError, match=message):
        link_as_transfer(conn, TENANT, _id(conn, a), _id(conn, b))


def test_linking_rejects_different_currencies_and_pending(conn: Connection) -> None:
    doc = _fixture_doc()
    next(a for a in doc["accounts"] if a["id"] == "wal")["currency"] = "EUR"
    ingest(conn, TENANT, pull_from_text(json.dumps(doc)), UTC_TZ)
    with pytest.raises(ValueError, match="currencies"):
        link_as_transfer(conn, TENANT, _id(conn, "t11"), _id(conn, "w11"))

    doc = _fixture_doc()
    for account in doc["accounts"]:
        for txn in account["transactions"]:
            if txn["id"] == "s03":
                txn["pending"], txn["posted"] = True, 0
    ingest(conn, TENANT, pull_from_text(json.dumps(doc)), UTC_TZ)
    with pytest.raises(ValueError, match="pending"):
        link_as_transfer(conn, TENANT, _id(conn, "t03"), _id(conn, "s03"))


def test_linking_an_unknown_transaction_fails(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_transfers.json")

    with pytest.raises(LookupError):
        link_as_transfer(conn, TENANT, _id(conn, "t03"), 999999)


# --- confirm_transfer and the review list ---------------------------------


def test_the_review_list_holds_exactly_the_low_confidence_match(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_transfers.json")
    reconcile(conn, TENANT)

    result = list_low_confidence_matches(conn, TENANT)

    assert result.rows is not None and len(result.rows) == 1
    row = result.rows[0]
    assert (row.amount, row.gap_days) == (Decimal("40.00"), 0)
    assert (row.out_account, row.out_date, row.out_description) == (
        "Demo Wallet",
        date(2026, 3, 14),
        "CASH OUT",
    )
    assert (row.in_account, row.in_date, row.in_description) == (
        "Demo Checking",
        date(2026, 3, 14),
        "DEPOSIT",
    )
    assert result.query == "low_confidence_transfer_matches"
    assert len(result.result_id) == 32 and result.data_version.startswith("dv_")
    assert result.as_of.tzinfo is not None and result.amounts_in


def test_the_review_list_is_empty_when_there_is_nothing_to_review(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_demo.json")
    reconcile(conn, TENANT)

    result = list_low_confidence_matches(conn, TENANT)

    assert result.rows == []


def test_confirming_removes_it_from_the_list_and_makes_it_permanent(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_transfers.json")
    reconcile(conn, TENANT)
    group = list_low_confidence_matches(conn, TENANT).rows[0].group_id  # type: ignore[index]

    confirm_transfer(conn, TENANT, group)
    confirm_transfer(conn, TENANT, group)  # idempotent

    assert list_low_confidence_matches(conn, TENANT).rows == []
    assert _state(conn, "t11", "w11") == [(True, True, "user"), (True, True, "user")]
    doc = _break(_fixture_doc(), "w11", "-40.01")  # upstream now disagrees
    ingest(conn, TENANT, pull_from_text(json.dumps(doc)), UTC_TZ)
    reconcile(conn, TENANT)
    assert _state(conn, "t11", "w11") == [(True, True, "user"), (True, True, "user")]


def test_rejecting_a_low_confidence_match_returns_the_rows_and_sticks(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_transfers.json")
    reconcile(conn, TENANT)

    mark_not_transfer(conn, TENANT, _id(conn, "w11"))
    reconcile(conn, TENANT)

    assert list_low_confidence_matches(conn, TENANT).rows == []
    assert _state(conn, "t11", "w11") == [(False, False, "user"), (False, False, "user")]


def test_confirming_an_unknown_group_fails(conn: Connection) -> None:
    with pytest.raises(LookupError):
        confirm_transfer(conn, TENANT, 999999)


# --- roles and the data version -------------------------------------------


def test_setting_a_role_is_a_user_decision_that_a_reingest_keeps(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_transfers.json")
    card = _account_id(conn, "cc")

    set_account_role(conn, TENANT, card, "credit")
    ingest_file(conn, TENANT, "simplefin_transfers.json")

    row = conn.execute("SELECT role, role_source FROM accounts WHERE id = %s", (card,)).fetchone()
    assert row == ("credit", "user")


def test_setting_the_same_role_twice_writes_nothing(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_transfers.json")
    card = _account_id(conn, "cc")
    set_account_role(conn, TENANT, card, "credit")
    before = conn.execute("SELECT xmin::text FROM accounts WHERE id = %s", (card,)).fetchone()

    set_account_role(conn, TENANT, card, "credit")

    assert (
        conn.execute("SELECT xmin::text FROM accounts WHERE id = %s", (card,)).fetchone() == before
    )


def test_setting_an_invalid_role_or_unknown_account_fails(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_transfers.json")

    with pytest.raises(ValueError, match="role"):
        set_account_role(conn, TENANT, _account_id(conn, "cc"), "savings")
    with pytest.raises(LookupError):
        set_account_role(conn, TENANT, 999999, "credit")


def test_the_data_version_changes_with_decisions_and_not_without(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_transfers.json")
    v0, as_of = data_stamp(conn, TENANT)
    assert data_stamp(conn, TENANT)[0] == v0
    assert as_of.tzinfo is UTC or as_of.utcoffset() is not None

    reconcile(conn, TENANT)
    v1 = data_stamp(conn, TENANT)[0]
    set_account_role(conn, TENANT, _account_id(conn, "cc"), "credit")
    v2 = data_stamp(conn, TENANT)[0]

    assert len({v0, v1, v2}) == 3
    assert data_stamp(conn, "nobody")[1].year == 1970


# --- review-driven hardening ----------------------------------------------


def test_linking_over_a_user_owned_group_is_refused_and_changes_nothing(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_transfers.json")
    link_as_transfer(conn, TENANT, _id(conn, "t10a"), _id(conn, "s10a"))  # the user's group

    with pytest.raises(ValueError, match="already in a transfer you decided"):
        link_as_transfer(conn, TENANT, _id(conn, "t10a"), _id(conn, "s10b"))

    assert _state(conn, "t10a", "s10a") == [(True, True, "user"), (True, True, "user")]
    assert _state(conn, "s10b") == [(False, False, None)]


@pytest.mark.parametrize("action", ["reconcile", "mark_not_transfer", "link", "confirm"])
def test_reconcile_and_actions_wait_for_the_tenant_lock(conn: Connection, action: str) -> None:
    import threading

    import psycopg

    from finance_agent.reconcile.match import lock_tenant
    from tests.helpers import database_url

    ingest_file(conn, TENANT, "simplefin_transfers.json")
    reconcile(conn, TENANT)
    t07, t06, s06 = _id(conn, "t07"), _id(conn, "t06"), _id(conn, "s06")
    group = conn.execute("SELECT min(id) FROM transfer_groups").fetchone()
    assert group is not None
    calls: dict[str, Callable[[], object]] = {
        "reconcile": lambda: reconcile(conn, TENANT),
        "mark_not_transfer": lambda: mark_not_transfer(conn, TENANT, t07),
        "link": lambda: link_as_transfer(conn, TENANT, t06, s06),
        "confirm": lambda: confirm_transfer(conn, TENANT, int(group[0])),
    }
    errors: list[BaseException] = []

    def run() -> None:
        try:
            calls[action]()
        except BaseException as error:  # surfaced below
            errors.append(error)

    with psycopg.connect(database_url()) as holder:  # a second session holds the lock
        lock_tenant(holder, TENANT)
        thread = threading.Thread(target=run)
        thread.start()
        thread.join(timeout=0.7)
        assert thread.is_alive(), f"{action} did not wait for the tenant lock"
        holder.commit()  # releases the lock
        thread.join(timeout=10)

    assert not thread.is_alive() and errors == []
