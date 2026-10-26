"""Starter rules: the set itself, seeding, and that real statement variants resolve."""

from itertools import combinations

import pytest

from finance_agent.categorize.enrich import normalize_merchant
from finance_agent.categorize.rules import FUZZY_THRESHOLD, categorize
from finance_agent.categorize.starter_rules import STARTER_RULES, seed_starter_rules
from finance_agent.db.default_categories import DEFAULT_CATEGORIES
from finance_agent.db.loader import Connection
from tests.categorize_helpers import TENANT, Txn, add_rule, load, state, versions

# Realistic statement variants for every brand (at least two each). Each must normalize to
# the brand's key exactly.
VARIANTS: dict[str, list[str]] = {
    "KROGER": ["KROGER #0421", "Kroger Store 5501", "KROGER 0421"],
    "SAFEWAY": ["SAFEWAY #1771", "Safeway Store 1771"],
    "WHOLE FOODS": ["WHOLE FOODS #10234", "Whole Foods 10234"],
    "TRADER JOES": ["TRADER JOE'S #123", "Trader Joe's Store 123"],
    "PUBLIX": ["PUBLIX #0412", "Publix 0412"],
    "STARBUCKS": ["STARBUCKS #1234", "Starbucks Store 5501", "STARBUCKS 0042"],
    "MCDONALDS": ["MCDONALD'S #5501", "McDonald's Store 5501"],
    "CHIPOTLE": ["CHIPOTLE #2040", "Chipotle 2040"],
    "SUBWAY": ["SUBWAY #1177", "Subway Store 1177"],
    "DUNKIN": ["DUNKIN #3350", "Dunkin 3350"],
    "DOMINOS": ["DOMINO'S 1234", "Dominos #1234"],
    "PANERA BREAD": ["PANERA BREAD #204", "Panera Bread 204"],
    "SHELL": ["SHELL #574", "Shell 57444"],
    "CHEVRON": ["CHEVRON #0042", "Chevron 0042"],
    "EXXONMOBIL": ["EXXONMOBIL 47512345", "ExxonMobil #4751"],
    "UBER": ["UBER", "UBER 0042", "Uber #1234"],
    "LYFT": ["LYFT", "Lyft #1234", "LYFT 0042"],
    "NETFLIX": ["NETFLIX", "NETFLIX 03/09", "Netflix 0042"],
    "SPOTIFY": ["SPOTIFY", "PAYPAL *SPOTIFY", "Spotify 0042"],
    "HULU": ["HULU", "HULU 03/09/2026"],
    "DISNEY PLUS": ["DISNEY PLUS", "Disney Plus 0042"],
    "XFINITY": ["XFINITY", "XFINITY 0042"],
    "VERIZON": ["VERIZON", "VERIZON 0042"],
    "ATT": ["AT&T", "AT&T 0042"],
    "CVS PHARMACY": ["CVS/PHARMACY #4321", "CVS PHARMACY 4321"],
    "WALGREENS": ["WALGREENS #4321", "Walgreens Store 4321"],
    "HOME DEPOT": ["HOME DEPOT #1234", "Home Depot 1234"],
    "BEST BUY": ["BEST BUY #0042", "Best Buy 0042"],
    "DELTA AIR LINES": ["DELTA AIR LINES 0062123456789", "Delta Air Lines"],
    "AIRBNB": ["AIRBNB", "AIRBNB 0042"],
}


def test_the_set_has_about_thirty_unique_keys() -> None:
    keys = [key for key, _ in STARTER_RULES]

    assert 28 <= len(keys) <= 32
    assert len(set(keys)) == len(keys)


def test_every_key_is_already_in_normalized_form() -> None:
    for key, _ in STARTER_RULES:
        assert normalize_merchant(key) == key, key


def test_every_category_is_in_the_default_taxonomy() -> None:
    names = {name for _, name in DEFAULT_CATEGORIES}

    assert {category for _, category in STARTER_RULES} <= names


def test_deliberately_ambiguous_brands_are_not_in_the_set() -> None:
    keys = {key for key, _ in STARTER_RULES}

    assert not keys & {"AMAZON", "AMAZON MARKETPLACE", "TARGET", "WALMART", "COSTCO", "APPLE"}


def test_the_variant_table_covers_every_brand_with_at_least_two() -> None:
    assert set(VARIANTS) == {key for key, _ in STARTER_RULES}
    assert all(len(v) >= 2 for v in VARIANTS.values())


@pytest.mark.parametrize("brand", sorted(VARIANTS))
def test_each_variant_normalizes_to_its_brand_key(brand: str) -> None:
    assert {normalize_merchant(v) for v in VARIANTS[brand]} == {brand}


def test_no_two_starter_keys_are_close_enough_to_be_confused(conn: Connection) -> None:
    keys = [key for key, _ in STARTER_RULES]
    worst = 0.0
    for a, b in combinations(keys, 2):
        row = conn.execute("SELECT similarity(%s, %s)", (a, b)).fetchone()
        assert row is not None
        worst = max(worst, float(row[0]))

    assert worst < FUZZY_THRESHOLD, f"two starter keys are {worst:.2f} similar"


# --- seeding ------------------------------------------------------------------------


def test_seeding_inserts_every_rule_as_a_rule_sourced_row(conn: Connection) -> None:
    result = seed_starter_rules(conn, TENANT)

    assert (result.inserted, result.skipped_unknown_category) == (len(STARTER_RULES), 0)
    rows = conn.execute(
        "SELECT merchant_normalized, category, source FROM merchant_rules"
    ).fetchall()
    assert {(k, c, s) for k, c, s in rows} == {(k, c, "rule") for k, c in STARTER_RULES}


def test_seeding_twice_writes_nothing_the_second_time(conn: Connection) -> None:
    seed_starter_rules(conn, TENANT)
    before = versions(conn, "merchant_rules")

    again = seed_starter_rules(conn, TENANT)

    assert (again.inserted, again.skipped_unknown_category) == (0, 0)
    assert versions(conn, "merchant_rules") == before


def test_seeding_never_overwrites_an_existing_user_rule(conn: Connection) -> None:
    add_rule(conn, "STARBUCKS", "shopping", "user")

    seed_starter_rules(conn, TENANT)

    row = conn.execute(
        "SELECT category, source FROM merchant_rules WHERE merchant_normalized = 'STARBUCKS'"
    ).fetchone()
    assert row == ("shopping", "user")


def test_a_tenant_missing_a_category_skips_those_rules_and_counts_them(conn: Connection) -> None:
    conn.execute("DELETE FROM categories WHERE name IN ('travel', 'health')")

    result = seed_starter_rules(conn, TENANT)

    assert result.skipped_unknown_category == 4  # CVS PHARMACY, WALGREENS, DELTA, AIRBNB
    assert result.inserted == len(STARTER_RULES) - 4
    count = conn.execute(
        "SELECT count(*) FROM merchant_rules WHERE category IN ('travel', 'health')"
    ).fetchone()
    assert count == (0,)


def test_seeding_one_tenant_does_not_touch_another(conn: Connection) -> None:
    seed_starter_rules(conn, TENANT)

    count = conn.execute("SELECT count(*) FROM merchant_rules WHERE tenant_id <> %s", (TENANT,))
    assert count.fetchone() == (0,)


# --- the rules do their job -----------------------------------------------------------


def test_every_variant_of_every_brand_gets_the_brand_category(conn: Connection) -> None:
    txns = [
        Txn(f"{brand}/{n}", raw) for brand, raws in VARIANTS.items() for n, raw in enumerate(raws)
    ]
    load(conn, txns)
    seed_starter_rules(conn, TENANT)

    result = categorize(conn, TENANT)

    expected = dict(STARTER_RULES)
    got = state(conn)
    assert result.uncategorized == 0 and result.assigned == len(txns)
    for txn in txns:
        brand = txn.id.split("/")[0]
        assert got[txn.id] == (expected[brand], "rule"), txn.desc


def test_uber_eats_is_not_an_uber_ride(conn: Connection) -> None:
    load(conn, [Txn("ride", "UBER #1234"), Txn("food", "UBER EATS"), Txn("food2", "UBER *EATS")])
    seed_starter_rules(conn, TENANT)

    categorize(conn, TENANT)

    assert state(conn) == {
        "ride": ("transport", "rule"),
        "food": (None, None),
        "food2": (None, None),
    }


@pytest.mark.parametrize(
    "lookalike", ["SHELL OIL", "SUBWAY TOKEN VENDING", "WHOLE FOODS MARKET", "CHEVROLET", "DELTA"]
)
def test_near_names_are_not_swept_up_by_a_starter_rule(conn: Connection, lookalike: str) -> None:
    load(conn, [Txn("a", lookalike)])
    seed_starter_rules(conn, TENANT)

    categorize(conn, TENANT)

    assert state(conn) == {"a": (None, None)}
