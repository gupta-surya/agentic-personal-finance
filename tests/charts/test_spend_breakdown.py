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
        "spend_breakdown", {"period": period, **extra}, catalog or FakeSeriesCatalog(), TODAY
    )


def points(spec: ChartSpec, series_id: str) -> list[tuple[str, Decimal | None]]:
    series = next(s for s in spec.series if s.id == series_id)
    return [(p.x, p.y) for p in series.points]


def test_march_amounts_and_shares_are_the_catalogs_in_the_catalogs_order() -> None:
    spec = render()

    assert points(spec, "amount") == [
        ("Rent", Decimal("1500.00")),
        ("Groceries", Decimal("366.20")),  # refund netted
        ("Dining", Decimal("94.50")),
        ("Transport", Decimal("52.66")),
        ("Uncategorized", Decimal("19.99")),
    ]
    assert points(spec, "share") == [
        ("Rent", Decimal("0.7377")),
        ("Groceries", Decimal("0.1801")),
        ("Dining", Decimal("0.0465")),
        ("Transport", Decimal("0.0259")),
        ("Uncategorized", Decimal("0.0098")),
    ]
    assert [s.kind for s in spec.series] == ["bar", "point"]


def test_title_states_the_largest_share_and_the_total_is_a_cited_fact() -> None:
    spec = render()

    assert spec.title == "Rent took the biggest share of spending, 73.77%, Mar 2026"
    total = next(a for a in spec.assumptions if a.key == "total")
    assert (total.value, total.source) == ("$2,033.35", "data")
    assert {s.result_id for s in spec.series} == {src.result_id for src in spec.sources}


def test_table_shows_formatted_amount_and_share() -> None:
    spec = render()

    assert spec.table.columns == ["Category", "Spend", "Share"]
    assert spec.table.rows[0] == ["Rent", "$1,500.00", "73.77%"]
    assert spec.table.rows[-1] == ["Uncategorized", "$19.99", "0.98%"]


def test_top_n_folds_into_a_labelled_bucket_with_the_catalogs_share() -> None:
    spec = render(top_n=2)

    assert points(spec, "amount") == [
        ("Rent", Decimal("1500.00")),
        ("Groceries", Decimal("366.20")),
        ("Everything else", Decimal("167.15")),
    ]
    assert spec.table.rows[-1] == ["Everything else", "$167.15", "8.22%"]


def test_a_group_with_refunds_above_spend_stays_visible_with_a_note() -> None:
    catalog = FakeSeriesCatalog(
        [SyntheticTransaction(date(2026, 3, 10), Decimal("50.00"), "groceries")]
    )
    spec = render(catalog=catalog)

    assert points(spec, "amount") == [("Groceries", Decimal("-50.00"))]
    assert spec.table.rows == [["Groceries", "−$50.00", "100%"]]
    assert spec.title == "Where your money went, Mar 2026"  # no "biggest share" claim
    assert [a.key for a in spec.assumptions if a.key == "refunds"] == ["refunds"]


def test_uncategorized_can_lead() -> None:
    catalog = FakeSeriesCatalog(
        [
            SyntheticTransaction(date(2026, 3, 2), Decimal("-90.00"), None),
            SyntheticTransaction(date(2026, 3, 3), Decimal("-10.00"), "rent"),
        ]
    )
    assert render(catalog=catalog).title.startswith("Uncategorized took the biggest share")


def test_no_data_gives_an_empty_spec() -> None:
    spec = render({"preset": "custom", "start": "2020-01-01", "end": "2020-02-01"})

    assert spec.series == [] and spec.table.rows == []
    assert spec.title == "Where your money went, Jan 2020"
    assert not [a for a in spec.assumptions if a.key == "total"]


def test_this_month_period_names_the_month_without_the_exclusive_end() -> None:
    spec = render({"preset": "this_month"})
    assert spec.title.endswith("Oct 2026")


def test_params_are_validated() -> None:
    with pytest.raises(ValidationError):
        render(group_by="merchant")
    with pytest.raises(ValidationError):
        render(top_n=0)
    with pytest.raises(ValidationError):
        render(filters="x")
