"""Transfer matching: pure pairing rules, then the fixture end to end against Postgres."""

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from finance_agent.db.loader import Connection
from finance_agent.ingest.pipeline import ingest
from finance_agent.reconcile.actions import mark_not_transfer
from finance_agent.reconcile.match import (
    WINDOW_DAYS,
    Leg,
    matched_keyword,
    pair_legs,
    reconcile,
)
from tests.helpers import FIXTURES, UTC_TZ, ingest_file, pull_from_text

TENANT = "demo-tenant"
D0 = date(2026, 3, 10)


def _leg(
    txn_id: int,
    account: int,
    amount: str,
    day: date = D0,
    currency: str = "USD",
    description: str = "x",
) -> Leg:
    return Leg(txn_id, account, currency, Decimal(amount), day, description)


# --- pure pairing ----------------------------------------------------------


def test_opposite_amounts_in_two_accounts_pair() -> None:
    pairing = pair_legs([_leg(1, 1, "-10.00"), _leg(2, 2, "10.00")])

    assert [(p.out_leg.txn_id, p.in_leg.txn_id, p.gap_days) for p in pairing.pairs] == [(1, 2, 0)]
    assert pairing.ambiguous_legs == frozenset()


@pytest.mark.parametrize(
    ("gap", "matches"), [(0, True), (WINDOW_DAYS, True), (WINDOW_DAYS + 1, False)]
)
def test_window_boundary(gap: int, matches: bool) -> None:
    legs = [_leg(1, 1, "-10.00"), _leg(2, 2, "10.00", D0 + timedelta(days=gap))]

    assert bool(pair_legs(legs).pairs) is matches


def test_the_window_is_seven_days() -> None:
    assert WINDOW_DAYS == 7


@pytest.mark.parametrize(
    "legs",
    [
        [_leg(1, 1, "-10.00"), _leg(2, 1, "10.00")],  # same account
        [_leg(1, 1, "-10.00"), _leg(2, 2, "10.01")],  # not exactly opposite
        [_leg(1, 1, "-10.00"), _leg(2, 2, "10.00", currency="EUR")],  # different currency
        [_leg(1, 1, "-10.00"), _leg(2, 2, "-10.00")],  # same direction
        [_leg(1, 1, "0.00"), _leg(2, 2, "0.00")],  # zero
    ],
    ids=["same-account", "amount-differs", "currency-differs", "same-direction", "zero"],
)
def test_pairs_that_must_not_form(legs: list[Leg]) -> None:
    assert pair_legs(legs).pairs == []


def test_nearest_date_wins_and_the_farther_leg_stays_unmatched() -> None:
    legs = [
        _leg(1, 1, "-100.00", D0),
        _leg(2, 2, "100.00", D0 + timedelta(days=1)),
        _leg(3, 2, "100.00", D0 + timedelta(days=4)),
    ]

    pairing = pair_legs(legs)

    assert [(p.out_leg.txn_id, p.in_leg.txn_id) for p in pairing.pairs] == [(1, 2)]
    assert pairing.ambiguous_legs == frozenset()


def test_equally_near_partners_are_a_tie_and_nothing_matches() -> None:
    legs = [
        _leg(1, 1, "-300.00", D0),
        _leg(2, 2, "300.00", D0 - timedelta(days=1)),
        _leg(3, 3, "300.00", D0 + timedelta(days=1)),
    ]

    pairing = pair_legs(legs)

    assert pairing.pairs == []
    assert pairing.ambiguous_legs == frozenset({1})


def test_a_tied_leg_does_not_fall_back_to_a_farther_partner() -> None:
    legs = [
        _leg(1, 1, "-300.00", D0),
        _leg(2, 2, "300.00", D0 - timedelta(days=1)),
        _leg(3, 3, "300.00", D0 + timedelta(days=1)),
        _leg(4, 4, "-300.00", D0 + timedelta(days=5)),  # would pair with leg 3 if it were free
    ]

    assert pair_legs(legs).pairs == []


def test_recurring_transfers_pair_month_to_month() -> None:
    months = [date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5)]
    legs = [_leg(10 + n, 1, "-500.00", d) for n, d in enumerate(months)]
    legs += [_leg(20 + n, 2, "500.00", d) for n, d in enumerate(months)]

    pairing = pair_legs(legs)

    assert [(p.out_leg.txn_id, p.in_leg.txn_id) for p in pairing.pairs] == [
        (10, 20),
        (11, 21),
        (12, 22),
    ]


def test_keyword_is_found_case_insensitively_and_only_recorded() -> None:
    assert matched_keyword("Online transfer to savings", "x") == "TRANSFER"
    assert matched_keyword("x", "ACH XFER IN") == "XFER"
    assert matched_keyword("AUTOPAY CARD", "PAYMENT THANK YOU") == "PAYMENT"
    assert matched_keyword("CASH OUT", "DEPOSIT") is None
    pairing = pair_legs([_leg(1, 1, "-10.00", description="CASH OUT"), _leg(2, 2, "10.00")])
    assert pairing.pairs[0].keyword is None and pairing.pairs[0].confidence == "low"


# --- the fixture, end to end ----------------------------------------------


def _ids(conn: Connection) -> dict[str, int]:
    return {r[0]: r[1] for r in conn.execute("SELECT external_id, id FROM transactions").fetchall()}


def _state(conn: Connection) -> dict[str, tuple[Any, ...]]:
    rows = conn.execute(
        "SELECT t.external_id, t.is_internal_transfer, t.transfer_source, g.match_confidence "
        "FROM transactions t LEFT JOIN transfer_groups g "
        "ON g.tenant_id = t.tenant_id AND g.id = t.transfer_group_id"
    ).fetchall()
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


def _groups(conn: Connection) -> dict[frozenset[str], tuple[Any, ...]]:
    rows = conn.execute(
        "SELECT g.id, g.match_confidence, g.evidence, g.rule, g.source, g.window_days, "
        "array_agg(t.external_id) FROM transfer_groups g "
        "JOIN transactions t ON t.transfer_group_id = g.id GROUP BY g.tenant_id, g.id ORDER BY g.id"
    ).fetchall()
    return {frozenset(r[6]): (r[1], r[2], r[3], r[4], r[5]) for r in rows}


def _load(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_transfers.json")
    # fixture row 8: the user already said these two are not a transfer
    conn.execute("UPDATE transactions SET transfer_source = 'user' WHERE external_id = 't08'")


MATCHED = {
    frozenset({"t03", "s03"}): "high",
    frozenset({"t04", "c04"}): "high",
    frozenset({"t10a", "s10a"}): "high",
    frozenset({"t10b", "s10b"}): "high",
    frozenset({"t11", "w11"}): "low",
}


def test_fixture_matches_exactly_the_expected_pairs(conn: Connection) -> None:
    _load(conn)

    result = reconcile(conn, TENANT)

    groups = _groups(conn)
    assert {k: v[0] for k, v in groups.items()} == MATCHED
    assert (result.matched, result.matched_low, result.updated) == (5, 1, 0)
    assert (result.dissolved, result.unchanged, result.ambiguous) == (0, 0, 1)
    flagged = {k for k, (internal, _, _) in _state(conn).items() if internal}
    assert flagged == {x for pair in MATCHED for x in pair}


def test_unmatched_fixture_rows_stay_spend_and_income(conn: Connection) -> None:
    _load(conn)
    reconcile(conn, TENANT)

    state = _state(conn)
    for ext in ("t01", "t02", "c05a", "c05b"):  # plain income and expenses
        assert state[ext] == (False, None, None)
    for ext in ("t06", "s06"):  # near-miss, 18 days apart
        assert state[ext] == (False, None, None)
    assert state["t07"] == (False, None, None)  # payment to a person
    assert state["t08"] == (False, "user", None)  # user said not a transfer
    assert state["s08"] == (False, None, None)  # its counterpart has no partner left
    for ext in ("t09", "s09", "c09"):  # equally near partners
        assert state[ext] == (False, None, None)


def test_evidence_for_the_clean_transfer_and_the_card_payment(conn: Connection) -> None:
    _load(conn)
    reconcile(conn, TENANT)
    ids = _ids(conn)
    groups = _groups(conn)

    clean = groups[frozenset({"t03", "s03"})]
    assert clean[1] == {
        "transaction_ids": [ids["t03"], ids["s03"]],
        "amount": "1000.00",
        "gap_days": 0,
        "keyword": "TRANSFER",
        "window_days": 7,
    }
    assert clean[2:] == ("nearest_date_exact_amount_v1", "rule", 7)
    card = groups[frozenset({"t04", "c04"})][1]
    assert (card["amount"], card["gap_days"], card["keyword"]) == ("500.00", 1, "PAYMENT")
    low = groups[frozenset({"t11", "w11"})][1]
    assert (low["amount"], low["gap_days"], low["keyword"]) == ("40.00", 0, None)


def test_a_second_run_changes_nothing(conn: Connection) -> None:
    _load(conn)
    reconcile(conn, TENANT)
    before = {
        table: conn.execute(f"SELECT id, xmin::text FROM {table} ORDER BY id").fetchall()
        for table in ("transactions", "transfer_groups")
    }

    again = reconcile(conn, TENANT)

    assert (again.matched, again.updated, again.dissolved, again.unchanged) == (0, 0, 0, 5)
    assert again.ambiguous == 1
    after = {
        table: conn.execute(f"SELECT id, xmin::text FROM {table} ORDER BY id").fetchall()
        for table in ("transactions", "transfer_groups")
    }
    assert after == before


def _fixture_doc() -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(
        (FIXTURES / "simplefin_transfers.json").read_text(encoding="utf-8")
    )
    return doc


def test_legs_arriving_in_different_pulls_match_on_the_later_run(conn: Connection) -> None:
    doc = _fixture_doc()
    first = {**doc, "accounts": [a for a in doc["accounts"] if a["id"] == "chk"]}
    rest = {**doc, "accounts": [a for a in doc["accounts"] if a["id"] != "chk"]}

    ingest(conn, TENANT, pull_from_text(json.dumps(first)), UTC_TZ)
    conn.execute("UPDATE transactions SET transfer_source = 'user' WHERE external_id = 't08'")
    assert reconcile(conn, TENANT).matched == 0

    ingest(conn, TENANT, pull_from_text(json.dumps(rest)), UTC_TZ)
    later = reconcile(conn, TENANT)

    assert later.matched == 5


def test_an_upstream_change_that_breaks_a_pair_dissolves_it(conn: Connection) -> None:
    _load(conn)
    reconcile(conn, TENANT)
    doc = _fixture_doc()
    for account in doc["accounts"]:
        for txn in account["transactions"]:
            if txn["id"] == "s03":
                txn["amount"] = "1000.01"

    ingest(conn, TENANT, pull_from_text(json.dumps(doc)), UTC_TZ)
    result = reconcile(conn, TENANT)

    assert (result.dissolved, result.matched, result.unchanged) == (1, 0, 4)
    state = _state(conn)
    assert state["t03"] == (False, None, None) and state["s03"] == (False, None, None)
    assert frozenset({"t03", "s03"}) not in _groups(conn)


def test_pending_rows_and_custom_currency_accounts_never_match(conn: Connection) -> None:
    doc = _fixture_doc()
    for account in doc["accounts"]:
        for txn in account["transactions"]:
            if txn["id"] in ("t03", "s03"):
                txn["pending"] = True
                txn["posted"] = 0
    wallet = next(a for a in doc["accounts"] if a["id"] == "wal")
    wallet["currency"] = "https://example.com/points"  # custom currency: never matched
    ingest(conn, TENANT, pull_from_text(json.dumps(doc)), UTC_TZ)

    reconcile(conn, TENANT)

    matched = {k for k in _groups(conn)}
    assert frozenset({"t03", "s03"}) not in matched
    assert frozenset({"t11", "w11"}) not in matched
    assert frozenset({"t04", "c04"}) in matched


# --- DB-level edge cases and the review list ------------------------------


def _body(*accounts: tuple[str, str, list[dict[str, Any]]]) -> str:
    """A v2 body: (account id, currency, transactions) tuples under one connection."""
    return json.dumps(
        {
            "errlist": [],
            "connections": [{"conn_id": "C", "name": "Bank"}],
            "accounts": [
                {
                    "id": acct,
                    "name": f"Acct {acct}",
                    "conn_id": "C",
                    "currency": currency,
                    "balance": "0",
                    "balance-date": 1774958400,
                    "transactions": txns,
                }
                for acct, currency, txns in accounts
            ],
        }
    )


def _t(txn_id: str, day: int, amount: str, desc: str) -> dict[str, Any]:
    posted = int(datetime(2026, 3, day, 12, tzinfo=UTC).timestamp())
    return {"id": txn_id, "posted": posted, "amount": amount, "description": desc}


def _ids2(conn: Connection) -> dict[str, int]:
    return {r[0]: r[1] for r in conn.execute("SELECT external_id, id FROM transactions").fetchall()}


def test_a_coincidental_match_at_the_window_edge_is_low_confidence_and_can_be_rejected(
    conn: Connection,
) -> None:
    body = _body(
        ("A", "USD", [_t("out", 3, "-250.00", "BOOKSTORE")]),
        ("B", "USD", [_t("in", 10, "250.00", "REFUND DEPOSIT")]),  # exactly 7 days later
    )
    ingest(conn, TENANT, pull_from_text(body), UTC_TZ)

    first = reconcile(conn, TENANT)
    assert (first.matched, first.matched_low) == (1, 1)

    mark_not_transfer(conn, TENANT, _ids2(conn)["out"])
    second = reconcile(conn, TENANT)

    assert (second.matched, second.dissolved) == (0, 0)
    assert _state(conn)["out"] == (False, "user", None)
    assert _state(conn)["in"] == (False, "user", None)


def test_eight_days_apart_does_not_match(conn: Connection) -> None:
    body = _body(
        ("A", "USD", [_t("out", 3, "-250.00", "TRANSFER")]),
        ("B", "USD", [_t("in", 11, "250.00", "TRANSFER")]),
    )
    ingest(conn, TENANT, pull_from_text(body), UTC_TZ)

    assert reconcile(conn, TENANT).matched == 0


def test_mixed_currencies_and_same_account_opposites_never_match(conn: Connection) -> None:
    body = _body(
        (
            "A",
            "USD",
            [_t("usd_out", 3, "-10.00", "TRANSFER"), _t("same_in", 3, "10.00", "TRANSFER")],
        ),
        ("B", "EUR", [_t("eur_in", 3, "10.00", "TRANSFER")]),
    )
    ingest(conn, TENANT, pull_from_text(body), UTC_TZ)

    result = reconcile(conn, TENANT)

    assert (result.matched, result.ambiguous) == (0, 0)
    assert not any(internal for internal, _, _ in _state(conn).values())


def test_the_review_list_is_ordered_by_posted_date_then_group_id(conn: Connection) -> None:
    from finance_agent.reconcile.review import list_low_confidence_matches

    # Inserted late-first, so group ids run opposite to dates; two pairs share a date.
    body = _body(
        (
            "A",
            "USD",
            [
                _t("late_out", 20, "-30.00", "x"),
                _t("early_out", 5, "-10.00", "x"),
                _t("tie1_out", 12, "-21.00", "x"),
                _t("tie2_out", 12, "-22.00", "x"),
            ],
        ),
        (
            "B",
            "USD",
            [
                _t("late_in", 20, "30.00", "y"),
                _t("early_in", 5, "10.00", "y"),
                _t("tie1_in", 12, "21.00", "y"),
                _t("tie2_in", 12, "22.00", "y"),
            ],
        ),
    )
    ingest(conn, TENANT, pull_from_text(body), UTC_TZ)
    reconcile(conn, TENANT)

    rows = list_low_confidence_matches(conn, TENANT).rows

    assert rows is not None
    assert [str(r.amount) for r in rows] == ["10.00", "21.00", "22.00", "30.00"]
    assert [r.group_id for r in rows[1:3]] == sorted(r.group_id for r in rows[1:3])
    group_ids = {r[0] for r in conn.execute("SELECT id FROM transfer_groups").fetchall()}
    assert {r.group_id for r in rows} == group_ids
