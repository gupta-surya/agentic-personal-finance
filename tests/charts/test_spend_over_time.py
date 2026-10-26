from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from finance_agent.charts.fake_catalog import FakeSeriesCatalog, SyntheticTransaction
from finance_agent.charts.spec import ChartSpec
from finance_agent.charts.templates import default_registry

TODAY = date(2026, 10, 25)
MAR_APR = {"preset": "custom", "start": "2026-03-01", "end": "2026-05-01"}


def render(
    period: dict[str, str] = MAR_APR,
    catalog: FakeSeriesCatalog | None = None,
    **extra: object,
) -> ChartSpec:
    return default_registry().render(
        "spend_over_time", {"period": period, **extra}, catalog or FakeSeriesCatalog(), TODAY
    )


def values(spec: ChartSpec, series_id: str) -> dict[str, Decimal | None]:
    series = next(s for s in spec.series if s.id == series_id)
    return {p.x: p.y for p in series.points}


def test_one_series_per_category_sorted_with_uncategorized_last() -> None:
    spec = render()

    assert [s.id for s in spec.series] == [
        "category:dining",
        "category:groceries",
        "category:rent",
        "category:transport",
        "uncategorized",
    ]
    assert [s.label for s in spec.series] == [
        "Dining",
        "Groceries",
        "Rent",
        "Transport",
        "Uncategorized",
    ]
    assert {s.kind for s in spec.series} == {"bar"}
    assert spec.title == "Spending by category, Mar 2026 – Apr 2026"


def test_values_are_the_catalogs_with_the_refund_netted_and_no_months_invented() -> None:
    spec = render()

    assert values(spec, "category:groceries")["2026-03-01"] == Decimal("366.20")  # refund netted
    assert values(spec, "uncategorized") == {"2026-03-01": Decimal("19.99")}  # no April zero
    expected = FakeSeriesCatalog().monthly_spend_by_category(
        date(2026, 3, 1), date(2026, 5, 1), "USD", top_n=6
    )
    assert expected.rows is not None
    plotted = {(s.id, p.x): p.y for s in spec.series for p in s.points}
    assert len(plotted) == len(expected.rows)
    assert {s.result_id for s in spec.series} == {src.result_id for src in spec.sources}


def test_top_n_folds_the_rest_into_everything_else_using_the_catalog() -> None:
    spec = render(top_n=2)

    assert [s.id for s in spec.series] == ["category:groceries", "category:rent", "everything_else"]
    assert spec.series[-1].label == "Everything else"
    assert values(spec, "everything_else")["2026-03-01"] == Decimal("167.15")
    assert [a.value for a in spec.assumptions if a.key == "top_n"] == [
        "Top 2; the rest are grouped as Everything else"
    ]


def test_a_real_category_named_other_is_not_the_folded_bucket() -> None:
    catalog = FakeSeriesCatalog(
        [
            SyntheticTransaction(date(2026, 3, 2), Decimal("-10.00"), "other"),
            SyntheticTransaction(date(2026, 3, 3), Decimal("-20.00"), "rent"),
            SyntheticTransaction(date(2026, 3, 4), Decimal("-30.00"), "dining"),
        ]
    )
    spec = render(catalog=catalog, top_n=2)

    assert [s.label for s in spec.series] == ["Dining", "Rent", "Everything else"]
    wide = render(catalog=catalog, top_n=12)
    assert "Other" in [s.label for s in wide.series]
    assert "Everything else" not in [s.label for s in wide.series]


def test_explicit_categories_select_without_re_ranking_or_folding() -> None:
    spec = render(categories=["groceries"])

    assert [s.id for s in spec.series] == ["category:groceries"]
    assert spec.series[0].kind == "line"  # one or two series are lines
    assert spec.title == "Groceries spending, Mar 2026 – Apr 2026"
    assert [a.value for a in spec.assumptions if a.key == "categories"] == ["Groceries"]
    assert not [a for a in spec.assumptions if a.key == "top_n"]


def test_table_has_one_row_per_month_and_blanks_where_there_is_no_spend() -> None:
    spec = render()

    assert spec.table.columns == [
        "Month",
        "Dining",
        "Groceries",
        "Rent",
        "Transport",
        "Uncategorized",
    ]
    assert spec.table.rows[0] == ["Mar 2026", "$94.50", "$366.20", "$1,500.00", "$52.66", "$19.99"]
    assert spec.table.rows[1][-1] is None  # no uncategorized spend in April


def test_no_data_gives_an_empty_spec() -> None:
    spec = render({"preset": "custom", "start": "2020-01-01", "end": "2020-02-01"})

    assert spec.series == [] and spec.table.rows == []
    assert spec.title == "Spending by category, Jan 1, 2020 – Jan 31, 2020"


def test_params_are_validated() -> None:
    with pytest.raises(ValidationError):
        render(top_n=0)
    with pytest.raises(ValidationError):
        render(top_n=13)
    with pytest.raises(ValidationError):
        render(interval="weekly")


def test_currency_is_never_mixed() -> None:
    spec = render(currency="EUR")
    assert [s.id for s in spec.series] == ["category:dining"]
    assert spec.table.rows == [["Mar 2026", "€30.00"]]
