from datetime import date
from decimal import Decimal

import pytest

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


def test_march_spend_breakdown_exact_values_and_shares() -> None:
    result = catalog().spend_breakdown(MAR, APR, "USD")

    assert result.rows is not None
    assert [(r.group, r.amount, r.share, r.is_other) for r in result.rows] == [
        ("rent", Decimal("1500.00"), Decimal("0.7377"), False),
        ("groceries", Decimal("366.20"), Decimal("0.1801"), False),
        ("dining", Decimal("94.50"), Decimal("0.0465"), False),
        ("transport", Decimal("52.66"), Decimal("0.0259"), False),
        (None, Decimal("19.99"), Decimal("0.0098"), False),
    ]
    assert result.totals == {"spend": Decimal("2033.35")}
    assert sum(r.share for r in result.rows) == Decimal("1.0000")


def test_spend_breakdown_top_n_folds_the_rest_into_a_flagged_bucket() -> None:
    result = catalog().spend_breakdown(MAR, APR, "USD", top_n=2)

    assert result.rows is not None
    assert [(r.group, r.amount, r.is_other) for r in result.rows] == [
        ("rent", Decimal("1500.00"), False),
        ("groceries", Decimal("366.20"), False),
        (None, Decimal("167.15"), True),  # dining + transport + uncategorized
    ]
    assert result.rows[-1].share == Decimal("0.0822")
    assert result.totals == {"spend": Decimal("2033.35")}
    assert result.params["top_n"] == 2


def test_spend_breakdown_empty_range_has_no_rows_or_totals() -> None:
    result = catalog().spend_breakdown(date(2020, 1, 1), date(2020, 2, 1), "USD")
    assert result.rows == []
    assert result.totals == {}


def test_series_top_n_folds_per_month_and_keeps_the_totals() -> None:
    plain = catalog().monthly_spend_by_category(MAR, date(2026, 5, 1), "USD")
    folded = catalog().monthly_spend_by_category(MAR, date(2026, 5, 1), "USD", top_n=2)

    assert folded.rows is not None and plain.rows is not None
    assert folded.totals == plain.totals
    march = [r for r in folded.rows if r.month == MAR]
    assert [(r.category, r.is_other) for r in march] == [
        ("groceries", False),
        ("rent", False),
        (None, True),
    ]
    assert march[-1].spend == Decimal("167.15")
    assert sum(r.is_other for r in folded.rows) == 2  # one folded row per month


def test_top_n_must_be_positive() -> None:
    with pytest.raises(ValueError, match="top_n"):
        catalog().spend_breakdown(MAR, APR, "USD", top_n=0)


def test_kpi_values_match_the_other_queries() -> None:
    fake = catalog()
    assert fake.kpi("spend", MAR, APR, "USD").value == Decimal("2033.35")
    assert fake.kpi("income", MAR, APR, "USD").value == Decimal("3200.00")
    assert fake.kpi("net", MAR, APR, "USD").value == Decimal("1166.65")
    groceries = fake.kpi("spend", MAR, APR, "USD", category="groceries")
    assert groceries.value == Decimal("366.20")  # refund netted
    assert groceries.rows is None
    assert groceries.params["category"] == "groceries"


def test_kpi_with_no_activity_is_zero_and_category_needs_spend() -> None:
    empty = catalog().kpi("spend", date(2020, 1, 1), date(2020, 2, 1), "USD")
    assert empty.value == Decimal("0")
    with pytest.raises(ValueError, match="category"):
        catalog().kpi("income", MAR, APR, "USD", category="groceries")
