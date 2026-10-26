"""Corrections become rules; user decisions are never overwritten."""

import threading
from collections.abc import Callable

import psycopg
import pytest

from finance_agent.categorize.actions import correct_category, delete_rule, set_rule
from finance_agent.categorize.rules import categorize, lock_categorization
from finance_agent.categorize.starter_rules import seed_starter_rules
from finance_agent.db.loader import Connection
from tests.categorize_helpers import TENANT, Txn, add_rule, keys, load, state
from tests.helpers import database_url, ingest_file


def _id(conn: Connection, external_id: str) -> int:
    row = conn.execute(
        "SELECT id FROM transactions WHERE external_id = %s", (external_id,)
    ).fetchone()
    assert row is not None
    return int(row[0])


def _rule(conn: Connection, key: str) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT category, source FROM merchant_rules WHERE merchant_normalized = %s", (key,)
    ).fetchone()
    return None if row is None else (row[0], row[1])


# --- correct_category ---------------------------------------------------------------


def test_a_correction_sets_the_row_makes_a_rule_and_updates_the_merchants_other_rows(
    conn: Connection,
) -> None:
    load(conn, [Txn("a", "CORNER MARKET 0042"), Txn("b", "Corner Market #7"), Txn("x", "MYSTERY")])

    correct_category(conn, TENANT, _id(conn, "a"), "groceries")

    assert state(conn) == {
        "a": ("groceries", "user"),
        "b": ("groceries", "rule"),  # followed the new rule
        "x": (None, None),
    }
    assert _rule(conn, "CORNER MARKET") == ("groceries", "user")
    assert keys(conn)["a"] == "CORNER MARKET"


def test_a_correction_leaves_a_different_user_set_row_alone(conn: Connection) -> None:
    load(conn, [Txn("a", "CORNER MARKET 0042"), Txn("mine", "CORNER MARKET #7")])
    correct_category(conn, TENANT, _id(conn, "mine"), "dining")  # the user's own choice

    correct_category(conn, TENANT, _id(conn, "a"), "groceries")

    assert state(conn) == {"a": ("groceries", "user"), "mine": ("dining", "user")}
    assert _rule(conn, "CORNER MARKET") == ("groceries", "user")  # latest correction wins the rule


def test_a_transfer_leg_cannot_be_corrected_into_a_category(conn: Connection) -> None:
    load(conn, [Txn("t", "ONLINE TRANSFER")])
    conn.execute("UPDATE transactions SET is_internal_transfer = true WHERE external_id = 't'")

    with pytest.raises(ValueError, match="internal transfer"):
        correct_category(conn, TENANT, _id(conn, "t"), "dining")

    assert state(conn) == {"t": (None, None)}
    assert _rule(conn, "ONLINE TRANSFER") is None


def test_a_correction_rejects_an_unknown_category_and_changes_nothing(conn: Connection) -> None:
    load(conn, [Txn("a", "CORNER MARKET")])

    with pytest.raises(ValueError, match="unknown category"):
        correct_category(conn, TENANT, _id(conn, "a"), "no_such_category")

    assert state(conn) == {"a": (None, None)}
    assert _rule(conn, "CORNER MARKET") is None


def test_a_correction_for_an_unknown_transaction_fails(conn: Connection) -> None:
    with pytest.raises(LookupError):
        correct_category(conn, TENANT, 999999, "groceries")


def test_a_description_with_no_merchant_sets_the_row_but_makes_no_rule(conn: Connection) -> None:
    load(conn, [Txn("a", "#1234"), Txn("b", "#5678")])

    correct_category(conn, TENANT, _id(conn, "a"), "other")

    assert state(conn) == {"a": ("other", "user"), "b": (None, None)}
    assert conn.execute("SELECT count(*) FROM merchant_rules").fetchone() == (0,)


def test_a_pending_row_can_be_corrected_and_stays_user_set(conn: Connection) -> None:
    load(conn, [Txn("p", "NEW CAFE 0042", pending=True), Txn("q", "NEW CAFE #9")])

    correct_category(conn, TENANT, _id(conn, "p"), "dining")
    categorize(conn, TENANT)

    assert state(conn) == {"p": ("dining", "user"), "q": ("dining", "rule")}


def test_a_correction_survives_reruns_a_competing_rule_and_a_reingest(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_demo.json")
    txn = _id(conn, "chk-txn-003")  # CORNER MARKET, hinted as groceries
    correct_category(conn, TENANT, txn, "dining")

    categorize(conn, TENANT)
    add_rule(conn, "CORNER MARKET", "shopping", "model")  # something else tries to win
    categorize(conn, TENANT)
    ingest_file(conn, TENANT, "simplefin_demo.json")  # the same payload arrives again
    categorize(conn, TENANT)

    assert state(conn)["chk-txn-003"] == ("dining", "user")


def test_a_correction_for_a_starter_merchant_replaces_it_and_survives_a_reseed(
    conn: Connection,
) -> None:
    load(conn, [Txn("a", "STARBUCKS #1"), Txn("b", "Starbucks Store 55")])
    seed_starter_rules(conn, TENANT)
    categorize(conn, TENANT)
    assert state(conn) == {"a": ("dining", "rule"), "b": ("dining", "rule")}
    assert _rule(conn, "STARBUCKS") == ("dining", "rule")

    correct_category(conn, TENANT, _id(conn, "a"), "shopping")
    categorize(conn, TENANT)
    seed_starter_rules(conn, TENANT)  # a re-seed must not bring the starter rule back
    categorize(conn, TENANT)

    assert _rule(conn, "STARBUCKS") == ("shopping", "user")
    assert state(conn) == {"a": ("shopping", "user"), "b": ("shopping", "rule")}


# --- set_rule ---------------------------------------------------------------------------


def test_set_rule_normalizes_the_merchant_and_applies_to_existing_rows(conn: Connection) -> None:
    load(conn, [Txn("a", "MCDONALD'S #5501"), Txn("b", "McDonald's Store 12")])

    set_rule(conn, TENANT, "McDonald's #99", "dining")

    assert _rule(conn, "MCDONALDS") == ("dining", "user")
    assert state(conn) == {"a": ("dining", "rule"), "b": ("dining", "rule")}


def test_set_rule_can_change_an_existing_rule_and_rows_follow(conn: Connection) -> None:
    load(conn, [Txn("a", "NETFLIX")])
    set_rule(conn, TENANT, "NETFLIX", "subscriptions")

    set_rule(conn, TENANT, "NETFLIX", "shopping")

    assert state(conn) == {"a": ("shopping", "rule")}


def test_set_rule_rejects_an_unknown_category_and_an_empty_merchant(conn: Connection) -> None:
    with pytest.raises(ValueError, match="unknown category"):
        set_rule(conn, TENANT, "NETFLIX", "no_such_category")
    with pytest.raises(ValueError, match="does not name a merchant"):
        set_rule(conn, TENANT, "#1234", "dining")

    assert conn.execute("SELECT count(*) FROM merchant_rules").fetchone() == (0,)


# --- delete_rule ------------------------------------------------------------------------


def test_deleting_a_rule_resets_only_the_rows_that_depended_on_it(conn: Connection) -> None:
    load(
        conn,
        [
            Txn("n1", "NETFLIX"),
            Txn("n2", "NETFLIX 03/09"),
            Txn("n_user", "NETFLIX 0042"),
            Txn("s1", "SPOTIFY"),
            Txn("other", "MYSTERY CORP"),
        ],
    )
    add_rule(conn, "NETFLIX", "subscriptions", "user")
    add_rule(conn, "SPOTIFY", "subscriptions", "rule")
    categorize(conn, TENANT)
    conn.execute(
        "UPDATE transactions SET category = 'dining', category_source = 'user' "
        "WHERE external_id = 'n_user'"
    )
    # a connector hint: rule-sourced, but no rule stands behind it
    conn.execute(
        "UPDATE transactions SET category = 'groceries', category_source = 'rule' "
        "WHERE external_id = 'other'"
    )

    delete_rule(conn, TENANT, "NETFLIX")

    assert state(conn) == {
        "n1": (None, None),
        "n2": (None, None),
        "n_user": ("dining", "user"),  # the user's own row stays
        "s1": ("subscriptions", "rule"),  # a different merchant is untouched
        "other": ("groceries", "rule"),  # a hint no deleted rule produced is untouched
    }
    assert _rule(conn, "NETFLIX") is None and _rule(conn, "SPOTIFY") is not None


def test_deleting_a_rule_resets_a_row_that_matched_it_only_fuzzily(conn: Connection) -> None:
    load(conn, [Txn("a", "GREENLEAF GROCER")])  # 0.82 similar to the rule, not equal
    add_rule(conn, "GREENLEAF GROCERS", "groceries", "user")
    categorize(conn, TENANT)
    assert state(conn) == {"a": ("groceries", "rule")}

    delete_rule(conn, TENANT, "GREENLEAF GROCERS")

    assert state(conn) == {"a": (None, None)}


def test_a_deleted_rule_hands_its_rows_to_another_matching_rule(conn: Connection) -> None:
    load(conn, [Txn("a", "GREENLEAF GROCERS")])
    add_rule(conn, "GREENLEAF GROCERS", "groceries", "user")
    add_rule(conn, "GREENLEAF GROCER", "shopping", "rule")  # a fuzzy neighbour
    categorize(conn, TENANT)
    assert state(conn) == {"a": ("groceries", "rule")}  # the exact rule wins

    delete_rule(conn, TENANT, "GREENLEAF GROCERS")

    assert state(conn) == {"a": ("shopping", "rule")}  # the fuzzy rule now applies


def test_deleting_a_rule_that_does_not_exist_fails(conn: Connection) -> None:
    with pytest.raises(LookupError):
        delete_rule(conn, TENANT, "NO SUCH MERCHANT")


# --- serialization ----------------------------------------------------------------------


@pytest.mark.parametrize("action", ["categorize", "correct", "set_rule", "delete_rule"])
def test_categorization_and_the_actions_wait_for_the_tenant_lock(
    conn: Connection, action: str
) -> None:
    load(conn, [Txn("a", "NETFLIX")])
    add_rule(conn, "NETFLIX", "subscriptions", "user")
    txn = _id(conn, "a")
    calls: dict[str, Callable[[], object]] = {
        "categorize": lambda: categorize(conn, TENANT),
        "correct": lambda: correct_category(conn, TENANT, txn, "dining"),
        "set_rule": lambda: set_rule(conn, TENANT, "SPOTIFY", "subscriptions"),
        "delete_rule": lambda: delete_rule(conn, TENANT, "NETFLIX"),
    }
    errors: list[BaseException] = []

    def run() -> None:
        try:
            calls[action]()
        except BaseException as error:
            errors.append(error)

    with psycopg.connect(database_url()) as holder:  # a second session holds the lock
        lock_categorization(holder, TENANT)
        thread = threading.Thread(target=run)
        thread.start()
        thread.join(timeout=0.7)
        assert thread.is_alive(), f"{action} did not wait for the tenant lock"
        holder.commit()
        thread.join(timeout=10)

    assert not thread.is_alive() and errors == []
