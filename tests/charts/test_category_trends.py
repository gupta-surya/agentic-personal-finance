from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from finance_agent.charts.fake_catalog import FakeSeriesCatalog, SyntheticTransaction
from finance_agent.charts.spec import ChartSpec
from finance_agent.charts.templates import default_registry

TODAY = date(2026, 10, 25)  # the window is Apr-Sep 2026 for 6 months


def render(catalog: FakeSeriesCatalog | None = None, **params: object) -> ChartSpec:
    return default_registry().render(
        "category_trends", params, catalog or FakeSeriesCatalog(), TODAY
    )


def row(spec: ChartSpec, label: str) -> list[str | None]:
    return next(r for r in spec.table.rows if r[0] == label)


def test_six_months_of_the_fake_data_with_every_figure_from_the_engine() -> None:
    spec = render()

    assert spec.title == "Category spending trends, Apr 2026 – Sep 2026"
    assert [r[0] for r in spec.table.rows] == ["Dining", "Groceries", "Rent", "Transport", "Travel"]
    assert row(spec, "Rent") == ["Rent", "$1,500.00", "$1,500.00", "$1,500.00", "0%", "– Flat"]
    # Travel is one 2,400.00 charge in June: months 1-3 hold it, months 4-6 do not
    assert row(spec, "Travel") == ["Travel", "$400.00", "$0.00", "$2,400.00", "−100%", "▼ Falling"]
    assert [s.query for s in spec.sources] == ["monthly_spend_by_category", "category_trends"]
    assert {s.result_id for s in spec.series} == {spec.sources[1].result_id}


def test_each_series_has_one_point_per_window_month_including_zeros() -> None:
    spec = render()
    travel = next(s for s in spec.series if s.id == "category:travel")

    assert [p.x for p in travel.points] == [
        "2026-04-01",
        "2026-05-01",
        "2026-06-01",
        "2026-07-01",
        "2026-08-01",
        "2026-09-01",
    ]
    assert [p.y for p in travel.points] == [
        Decimal(0),
        Decimal(0),
        Decimal("2400.00"),
        Decimal(0),
        Decimal(0),
        Decimal(0),
    ]
    assert all(s.kind == "line" for s in spec.series)


def test_rising_and_the_change_text_carry_a_sign() -> None:
    catalog = FakeSeriesCatalog(
        [
            SyntheticTransaction(date(2026, m, 5), Decimal(f"-{amount}"), "dining")
            for m, amount in [(4, 100), (5, 100), (6, 100), (7, 150), (8, 150), (9, 150)]
        ]
    )
    spec = render(catalog)

    assert row(spec, "Dining") == ["Dining", "$125.00", "$100.00", "$150.00", "+50%", "▲ Rising"]


def test_three_months_is_not_enough_to_show_a_direction() -> None:
    spec = render(months=3)

    assert {r[5] for r in spec.table.rows} == {"Not enough data"}
    assert {r[4] for r in spec.table.rows} == {"n/a"}
    assert spec.title == "Category spending trends, Jul 2026 – Sep 2026"


def test_a_year_of_months_and_the_window_ends_before_this_month() -> None:
    spec = render(months=12)
    assert spec.period is not None
    assert (spec.period.start, spec.period.end) == (date(2025, 10, 1), date(2026, 10, 1))
    assert len(spec.series[0].points) == 12


def test_top_n_folds_through_the_catalog_and_explicit_categories_select() -> None:
    folded = render(top_n=2)
    assert [r[0] for r in folded.table.rows] == ["Rent", "Travel", "Everything else"]

    chosen = render(categories=["groceries"])
    assert [r[0] for r in chosen.table.rows] == ["Groceries"]
    assert [a.value for a in chosen.assumptions if a.key == "categories"] == ["Groceries"]


def test_no_data_gives_an_empty_spec_and_one_source() -> None:
    spec = render(FakeSeriesCatalog([]))

    assert spec.series == [] and spec.table.rows == []
    assert [s.query for s in spec.sources] == ["monthly_spend_by_category"]


def test_currency_is_never_mixed() -> None:
    spec = render(currency="EUR", months=3)
    assert [r[0] for r in spec.table.rows] == []  # the only EUR charge is in March


def test_params_are_validated() -> None:
    for bad in ({"months": 2}, {"months": 13}, {"top_n": 0}, {"interval": "weekly"}):
        with pytest.raises(ValidationError):
            render(**bad)
