from datetime import date
from decimal import Decimal

from finance_agent.charts.fake_catalog import FakeSeriesCatalog
from finance_agent.queries.series import SeriesCatalog

MAR = date(2026, 3, 1)
APR = date(2026, 4, 1)


def catalog() -> SeriesCatalog:  # the annotation is the Protocol check under mypy
    return FakeSeriesCatalog()


def test_march_spend_exact_values_with_refund_and_uncategorized() -> None:
    result = catalog().monthly_spend_by_category(MAR, APR, "USD")

    assert result.rows is not None
    got = {(r.category): r.spend for r in result.rows}
    # groceries: 192.78 + 198.42 - 25.00 refund
    assert got == {
        "dining": Decimal("94.50"),  # the EUR charge is excluded
        "groceries": Decimal("366.20"),
        "rent": Decimal("1500.00"),
        "transport": Decimal("52.66"),
        None: Decimal("19.99"),
    }
    assert result.totals == {"spend": Decimal("2033.35")}
    assert [r.category for r in result.rows][-1] is None  # uncategorized sorts last


def test_march_cash_flow_exact_values() -> None:
    result = catalog().cash_flow(MAR, APR, "USD")

    assert result.rows is not None and len(result.rows) == 1
    row = result.rows[0]
    assert (row.inflow, row.outflow, row.net) == (
        Decimal("3225.00"),  # salary + the groceries refund (a credit)
        Decimal("2058.35"),
        Decimal("1166.65"),
    )
    assert result.totals == {
        "inflow": Decimal("3225.00"),
        "outflow": Decimal("2058.35"),
        "net": Decimal("1166.65"),
    }


def test_end_is_exclusive_and_ranges_can_start_mid_month() -> None:
    fake = FakeSeriesCatalog()
    # groceries: charge Mar 8, refund Mar 15, charge Mar 20. [Mar 9, Mar 15) has none of them
    result = fake.monthly_spend_by_category(date(2026, 3, 9), date(2026, 3, 15), "USD")
    assert result.rows is not None
    assert "groceries" not in {r.category for r in result.rows}
    refund_only = fake.monthly_spend_by_category(date(2026, 3, 9), date(2026, 3, 16), "USD")
    assert refund_only.rows is not None
    assert {r.category: r.spend for r in refund_only.rows}["groceries"] == Decimal("-25.00")
    partial = fake.monthly_spend_by_category(date(2026, 3, 9), date(2026, 3, 21), "USD")
    assert partial.rows is not None
    assert {r.category: r.spend for r in partial.rows}["groceries"] == Decimal("173.42")


def test_transfers_and_pending_are_excluded() -> None:
    fake = FakeSeriesCatalog()
    feb = fake.cash_flow(date(2026, 2, 1), MAR, "USD")
    assert feb.rows is not None
    assert feb.rows[0].inflow == Decimal("3200.00")  # the +500 transfer leg is not income
    oct_ = fake.monthly_spend_by_category(date(2026, 10, 1), date(2026, 11, 1), "USD")
    assert oct_.rows is not None
    dining = next(r.spend for r in oct_.rows if r.category == "dining")
    assert dining == Decimal("87.50")  # the -50.00 pending charge is not counted


def test_currency_filter_never_mixes_currencies() -> None:
    result = catalog().monthly_spend_by_category(MAR, APR, "EUR")
    assert result.rows is not None
    assert [(r.category, r.spend) for r in result.rows] == [("dining", Decimal("30.00"))]


def test_empty_range_returns_empty_rows_and_no_totals() -> None:
    result = catalog().cash_flow(date(2020, 1, 1), date(2020, 2, 1), "USD")
    assert result.rows == []
    assert result.totals == {}


def test_results_are_deterministic_with_fresh_result_ids() -> None:
    first, second = FakeSeriesCatalog(), FakeSeriesCatalog()
    a1 = first.cash_flow(MAR, APR, "USD")
    a2 = first.cash_flow(MAR, APR, "USD")
    b1 = second.cash_flow(MAR, APR, "USD")
    assert a1.result_id != a2.result_id
    assert a1 == b1


def test_earliest_date_skips_pending_and_transfers() -> None:
    assert FakeSeriesCatalog().earliest_date() == date(2025, 9, 1)
    assert FakeSeriesCatalog([]).earliest_date() is None
