from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from finance_agent.charts.fake_catalog import FakeSeriesCatalog, SyntheticTransaction
from finance_agent.charts.spec import ChartSpec
from finance_agent.charts.templates import default_registry

TODAY = date(2026, 10, 25)
MARCH = {"preset": "custom", "start": "2026-03-01", "end": "2026-04-01"}


def render(
    period: dict[str, str] = MARCH,
    catalog: FakeSeriesCatalog | None = None,
    **extra: object,
) -> ChartSpec:
    return default_registry().render(
        "kpi", {"period": period, **extra}, catalog or FakeSeriesCatalog(), TODAY
    )


def point(spec: ChartSpec, series_id: str) -> Decimal | None:
    series = next((s for s in spec.series if s.id == series_id), None)
    return series.points[0].y if series else None


def test_march_spend_with_its_change_from_the_previous_31_days() -> None:
    spec = render()

    # Previous period = the 31 days before Mar 1, i.e. Jan 29 – Feb 28.
    assert point(spec, "current") == Decimal("2033.35")
    assert point(spec, "previous") == Decimal("1947.05")
    assert point(spec, "change") == Decimal("86.30")
    assert point(spec, "change_percent") == Decimal("0.0443")
    assert spec.title == "You spent $2,033.35, Mar 2026"
    assert spec.table.rows == [
        ["Mar 1, 2026 – Mar 31, 2026", "$2,033.35"],
        ["Previous period, Jan 29, 2026 – Feb 28, 2026", "$1,947.05"],
        ["Change", "+$86.30"],
        ["Change, percent", "+4.43%"],
    ]


def test_every_figure_traces_to_a_cited_result_including_the_engine() -> None:
    spec = render()

    assert [s.query for s in spec.sources] == ["kpi", "kpi", "period_delta"]
    assert {s.result_id for s in spec.series} == {s.result_id for s in spec.sources}
    delta_source = spec.sources[2].result_id
    assert delta_source == f"period_delta:{spec.sources[0].result_id}:{spec.sources[1].result_id}"
    assert next(s for s in spec.series if s.id == "change").result_id == delta_source


def test_category_refund_is_netted_and_named_in_the_title() -> None:
    spec = render(category="groceries")

    assert point(spec, "current") == Decimal("366.20")  # 192.78 + 198.42 - 25.00 refund
    assert spec.title == "You spent $366.20 on Groceries, Mar 2026"
    assert [a.value for a in spec.assumptions if a.key == "category"] == ["Groceries"]


def test_dining_change_in_both_amount_and_percent() -> None:
    spec = render(category="dining")

    assert point(spec, "current") == Decimal("94.50")
    assert point(spec, "change") == Decimal("29.00")
    assert point(spec, "change_percent") == Decimal("0.4427")


def test_income_is_unchanged_and_net_fell() -> None:
    income = render(measure="income")
    assert point(income, "current") == Decimal("3200.00")
    assert point(income, "change") == Decimal("0.00")
    assert point(income, "change_percent") == Decimal("0.0000")
    assert income.title == "You earned $3,200.00, Mar 2026"
    assert income.table.rows[2:] == [["Change", "$0.00"], ["Change, percent", "0%"]]

    net = render(measure="net")
    assert point(net, "current") == Decimal("1166.65")
    assert point(net, "change") == Decimal("-86.30")
    assert point(net, "change_percent") == Decimal("-0.0689")
    assert net.title == "Net cash flow was $1,166.65, Mar 2026"
    assert net.table.rows[2:] == [["Change", "−$86.30"], ["Change, percent", "−6.89%"]]


def test_a_zero_previous_period_has_no_percentage_never_infinity() -> None:
    # History starts in July, so August (the previous period) is covered but empty.
    catalog = FakeSeriesCatalog(
        [
            SyntheticTransaction(date(2025, 7, 15), Decimal("3200.00"), "income"),
            SyntheticTransaction(date(2025, 9, 3), Decimal("-120.00"), "groceries"),
        ]
    )
    spec = render({"preset": "custom", "start": "2025-09-01", "end": "2025-10-01"}, catalog)

    assert point(spec, "current") == Decimal("120.00")
    assert point(spec, "previous") == Decimal("0")
    assert point(spec, "change") == point(spec, "current")
    assert point(spec, "change_percent") is None  # no series at all
    assert "change_percent" not in [s.id for s in spec.series]
    assert spec.table.rows[-1] == ["Change, percent", "n/a"]


def test_no_data_is_a_zero_not_an_empty_state() -> None:
    spec = render({"preset": "custom", "start": "2020-01-01", "end": "2020-02-01"})

    assert point(spec, "current") == Decimal("0")
    assert spec.title == "You spent $0.00, Jan 2020"
    assert spec.table.rows[0][1] == "$0.00"


def test_this_month_is_compared_with_the_same_days_of_last_month() -> None:
    spec = render({"preset": "this_month"})  # Oct 1 – Oct 25

    assert [a.value for a in spec.assumptions if a.key == "compared_with"] == ["vs Sep 1–25"]
    assert spec.table.rows[1][0] == "Previous period, Sep 1, 2026 – Sep 25, 2026"


def test_last_month_is_compared_with_the_full_month_before() -> None:
    catalog = FakeSeriesCatalog()
    spec = render({"preset": "last_month"}, catalog)

    expected = catalog.kpi("spend", date(2026, 8, 1), date(2026, 9, 1), "USD")
    assert [a.value for a in spec.assumptions if a.key == "compared_with"] == ["vs Aug 2026"]
    assert point(spec, "previous") == expected.value
    assert [s.query for s in spec.sources] == ["kpi", "kpi", "period_delta"]


def test_currency_is_never_mixed() -> None:
    spec = render(currency="EUR")

    assert point(spec, "current") == Decimal("30.00")
    assert spec.table.rows[0][1] == "€30.00"
    assert spec.params["currency"] == "EUR"


def test_an_overspent_net_reads_naturally() -> None:
    catalog = FakeSeriesCatalog(
        [
            SyntheticTransaction(date(2026, 3, 1), Decimal("100.00"), "income"),
            SyntheticTransaction(date(2026, 3, 2), Decimal("-400.00"), "rent"),
        ]
    )
    spec = render(catalog=catalog, measure="net")

    assert spec.title == "Net cash flow was −$300.00, Mar 2026"
    assert point(spec, "current") == Decimal("-300.00")


def test_an_empty_string_category_is_a_category_not_all_spend() -> None:
    assert point(render(category=""), "current") == Decimal("0")


def test_params_are_validated() -> None:
    with pytest.raises(ValidationError, match="category applies only"):
        render(measure="income", category="groceries")
    with pytest.raises(ValidationError):
        render(measure="profit")
    with pytest.raises(ValidationError):
        render(interval="weekly")


# --- comparisons need the whole previous period (the "+1,327.7%" bug) -----------------
# The synthetic data starts Sep 1, 2025.


def test_twelve_months_of_thirteen_months_of_data_is_not_compared() -> None:
    spec = render({"preset": "last_12_months"})  # Oct 2025 – Sep 2026; previous from Oct 2024

    assert point(spec, "current") == Decimal("26705.17")
    assert [s.id for s in spec.series] == ["current"]  # no previous, change or percent
    assert [s.query for s in spec.sources] == ["kpi"]  # the partial total is never queried
    assert spec.title == "You spent $26,705.17, Oct 2025 – Sep 2026"
    assert spec.table.rows == [
        ["Oct 1, 2025 – Sep 30, 2026", "$26,705.17"],
        ["Previous period, Oct 1, 2024 – Sep 30, 2025", "Not enough history"],
        ["Change", "n/a"],
        ["Change, percent", "n/a"],
    ]
    assert [a.value for a in spec.assumptions if a.key == "compared_with"] == [
        "Not enough history: your USD data starts Sep 1, 2025"
    ]


def test_all_time_has_no_change() -> None:
    spec = render({"preset": "all_time"}, measure="net")

    assert [s.id for s in spec.series] == ["current"]
    assert spec.table.rows[2:] == [["Change", "n/a"], ["Change, percent", "n/a"]]


def test_six_months_is_still_compared_when_history_covers_the_previous_period() -> None:
    spec = render({"preset": "last_6_months"})  # previous Sep 30, 2025 – Mar 31, 2026

    assert [s.id for s in spec.series] == ["current", "previous", "change", "change_percent"]
    assert point(spec, "current") == Decimal("14609.67")
    # Oct–Mar outflows (cash_flow) total 12,120.50; spend nets March's 25.00 refund.
    assert point(spec, "previous") == Decimal("12095.50")
    assert point(spec, "change") == Decimal("2514.17")
    assert point(spec, "change_percent") == Decimal("0.2079")


def test_a_previous_period_starting_on_the_first_day_of_data_is_compared() -> None:
    first = date(2025, 9, 1)
    assert FakeSeriesCatalog().earliest_date() == first
    # Oct 1 – Oct 31 is 31 days, so its previous period, Aug 31 – Sep 30, starts a day early.
    early = render({"preset": "custom", "start": "2025-10-01", "end": "2025-11-01"})
    assert [s.id for s in early.series] == ["current"]
    # Oct 1 – Oct 30 (30 days) compares with Sep 1 – Sep 30, inside the data.
    inside = render({"preset": "custom", "start": "2025-10-01", "end": "2025-10-31"})
    assert "previous" in [s.id for s in inside.series]


def test_no_data_at_all_says_so() -> None:
    spec = render({"preset": "this_month"}, FakeSeriesCatalog([]))

    assert point(spec, "current") == Decimal("0")
    assert [a.value for a in spec.assumptions if a.key == "compared_with"] == [
        "Not enough history: there is no USD data yet"
    ]


def test_history_is_per_currency() -> None:
    # USD history from January; the EUR account only from June.
    catalog = FakeSeriesCatalog(
        [
            SyntheticTransaction(date(2026, 1, 5), Decimal("-100.00"), "groceries"),
            SyntheticTransaction(date(2026, 6, 3), Decimal("-40.00"), "dining", currency="EUR"),
            SyntheticTransaction(date(2026, 7, 3), Decimal("-60.00"), "dining", currency="EUR"),
        ]
    )
    july = {"preset": "custom", "start": "2026-07-01", "end": "2026-08-01"}  # previous from May 31

    eur = render(july, catalog, currency="EUR")
    assert [s.id for s in eur.series] == ["current"]
    assert point(eur, "current") == Decimal("60.00")
    assert [a.value for a in eur.assumptions if a.key == "compared_with"] == [
        "Not enough history: your EUR data starts Jun 3, 2026"
    ]
    assert "previous" in [s.id for s in render(july, catalog).series]  # USD covers May 31
