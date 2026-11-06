from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from finance_agent.engines.category_trends import TrendRow, category_trends
from finance_agent.queries.result import (
    AMOUNTS_IN_DECIMAL,
    MonthlyCategorySpendRow,
    QueryResult,
)

AS_OF = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def month(n: int) -> date:
    return date(2026, n, 1)


def window(count: int) -> list[date]:
    return [month(m) for m in range(1, count + 1)]


def source(
    *rows: tuple[str | None, int, str], other: bool = False
) -> QueryResult[MonthlyCategorySpendRow]:
    return QueryResult[MonthlyCategorySpendRow](
        query="monthly_spend_by_category",
        params={"currency": "USD"},
        result_id="res_1",
        data_version="dv_1",
        as_of=AS_OF,
        amounts_in=AMOUNTS_IN_DECIMAL,
        rows=[
            MonthlyCategorySpendRow(
                month=month(m), category=None if other else c, spend=Decimal(s), is_other=other
            )
            for c, m, s in rows
        ],
    )


def trend(spend: list[str], months: int | None = None) -> TrendRow:
    """The one row for a category spending ``spend`` in each of the first months."""
    rows = [("x", i + 1, s) for i, s in enumerate(spend)]
    result = category_trends(source(*rows), window(months or len(spend)))
    assert result.rows is not None and len(result.rows) == 1
    return result.rows[0]


def test_a_rise_a_fall_and_the_figures_that_go_with_them() -> None:
    up = trend(["100", "100", "150", "150"])
    assert (up.direction, up.change) == ("rising", Decimal("0.5000"))
    assert (up.average, up.minimum, up.maximum) == (
        Decimal("125.00"),
        Decimal("100"),
        Decimal("150"),
    )
    assert up.monthly == [Decimal(100), Decimal(100), Decimal(150), Decimal(150)]

    down = trend(["200", "200", "100", "100"])
    assert (down.direction, down.change) == ("falling", Decimal("-0.5000"))


@pytest.mark.parametrize(
    ("second_half_each", "direction", "change"),
    [
        ("52.50", "rising", "0.0500"),  # exactly +5%: a trend, not flat
        ("52.49", "flat", "0.0498"),  # just under
        ("47.50", "falling", "-0.0500"),  # exactly -5%
        ("47.51", "flat", "-0.0498"),
        ("50.00", "flat", "0.0000"),
    ],
)
def test_the_five_percent_boundary(second_half_each: str, direction: str, change: str) -> None:
    row = trend(["50", "50", second_half_each, second_half_each])
    assert (row.direction, row.change) == (direction, Decimal(change))


def test_the_badge_never_contradicts_the_displayed_change() -> None:
    # 4.996% rounds to the displayed +5.00%: it is a trend, not flat
    row = trend(["1000", "0", "1049.96", "0"])
    assert (row.change, row.direction) == (Decimal("0.0500"), "rising")
    # 4.994% rounds to 4.99%: flat
    row = trend(["1000", "0", "1049.94", "0"])
    assert (row.change, row.direction) == (Decimal("0.0499"), "flat")


def test_a_selection_is_applied_by_the_engine_and_recorded_in_its_params() -> None:
    rows = [("rent", 1, "5"), ("dining", 1, "5"), ("travel", 1, "5")]
    result = category_trends(source(*rows), window(4), only={"travel", "rent"})

    assert result.rows is not None
    assert [r.category for r in result.rows] == ["rent", "travel"]
    assert result.params["categories"] == ["rent", "travel"]
    assert "categories" not in category_trends(source(*rows), window(4)).params
    # the folded bucket is never selected by name
    folded = category_trends(source(("x", 1, "5"), other=True), window(4), only={"x"})
    assert folded.rows == []


def test_a_refund_month_nets_below_zero_and_is_kept() -> None:
    row = trend(["100", "100", "-25", "100"])  # month 3: a refund exceeded that month's spend

    assert row.minimum == Decimal("-25")
    assert row.average == Decimal("68.75")
    # halves: months 1-2 total 200, months 3-4 total 75 -> (75 - 200) / 200
    assert (row.direction, row.change) == ("falling", Decimal("-0.6250"))


def test_a_sparse_category_counts_its_empty_months_as_zero() -> None:
    result = category_trends(source(("x", 2, "60")), window(6))
    assert result.rows is not None
    row = result.rows[0]

    assert row.monthly == [Decimal(0), Decimal(60), Decimal(0), Decimal(0), Decimal(0), Decimal(0)]
    assert row.average == Decimal("10.00")  # 60 over 6 months, not over the 1 month with spend
    assert (row.minimum, row.maximum) == (Decimal(0), Decimal(60))
    assert row.direction == "falling"  # first three months 60, last three 0


def test_nothing_in_the_first_half_has_no_percentage_not_infinity() -> None:
    row = trend(["0", "0", "40", "40"])
    assert (row.direction, row.change) == ("rising", None)


def test_too_few_months_is_insufficient_data() -> None:
    row = trend(["10", "20", "30"])
    assert (row.direction, row.change) == ("insufficient_data", None)
    assert row.average == Decimal("20.00")  # the figures are still reported


def test_an_odd_window_leaves_the_middle_month_out_of_both_halves() -> None:
    # halves are months 1-2 and 4-5; month 3's spike must not move the direction
    row = trend(["100", "100", "9999", "100", "100"])
    assert (row.direction, row.change) == ("flat", Decimal("0.0000"))


def test_categories_sort_alphabetically_with_uncategorized_then_the_folded_bucket_last() -> None:
    rows = [("rent", 1, "5"), ("dining", 1, "5"), (None, 1, "5")]
    result = category_trends(source(*rows), window(4))
    assert result.rows is not None
    assert [r.category for r in result.rows] == ["dining", "rent", None]

    folded = category_trends(source(("x", 1, "5"), other=True), window(4))
    assert folded.rows is not None and [(r.category, r.is_other) for r in folded.rows] == [
        (None, True)
    ]


def test_the_result_names_its_source_and_the_window() -> None:
    result = category_trends(source(("x", 1, "5")), window(4))

    assert result.query == "category_trends"
    assert result.result_id == "category_trends:res_1"
    assert result.params["source_result_id"] == "res_1"
    assert result.params["months"] == ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"]
    assert (result.data_version, result.as_of) == ("dv_1", AS_OF)


def test_an_empty_source_gives_no_rows_and_bad_input_is_refused() -> None:
    assert category_trends(source(), window(4)).rows == []
    with pytest.raises(ValueError, match="at least one month"):
        category_trends(source(), [])
    scalar = source().model_copy(update={"rows": None, "value": Decimal(1)})
    with pytest.raises(ValueError, match="with rows"):
        category_trends(scalar, window(4))
