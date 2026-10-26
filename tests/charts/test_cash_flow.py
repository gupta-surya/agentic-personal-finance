from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from finance_agent.charts.api import create_app
from finance_agent.charts.fake_catalog import FakeSeriesCatalog, SyntheticTransaction
from finance_agent.charts.spec import ChartSpec
from finance_agent.charts.templates import default_registry

TODAY = date(2026, 10, 25)
MARCH = {"preset": "custom", "start": "2026-03-01", "end": "2026-04-01"}


def render(
    period: dict[str, str], catalog: FakeSeriesCatalog | None = None, **extra: str
) -> ChartSpec:
    return default_registry().render(
        "cash_flow", {"period": period, **extra}, catalog or FakeSeriesCatalog(), TODAY
    )


def contract_example_catalog() -> FakeSeriesCatalog:
    """The contract example's overspent March: inflow 3200.00, outflow 3410.75."""
    return FakeSeriesCatalog(
        [
            SyntheticTransaction(date(2026, 3, 1), Decimal("3200.00"), "income"),
            SyntheticTransaction(date(2026, 3, 3), Decimal("-3410.75"), "rent"),
        ]
    )


def points(spec: ChartSpec, series_id: str) -> list[tuple[str, Decimal | None]]:
    series = next(s for s in spec.series if s.id == series_id)
    return [(p.x, p.y) for p in series.points]


def test_golden_overspent_month_from_the_contract_example() -> None:
    spec = render(MARCH, contract_example_catalog())

    assert spec.title == "You spent more than you earned, Mar 2026: net −$210.75"
    assert points(spec, "inflow") == [("2026-03-01", Decimal("3200.00"))]
    assert points(spec, "outflow") == [("2026-03-01", Decimal("3410.75"))]
    assert points(spec, "net") == [("2026-03-01", Decimal("-210.75"))]
    assert spec.table.rows == [["Mar 2026", "$3,200.00", "$3,410.75", "−$210.75", "−$210.75"]]


def test_the_builder_claims_no_figure_that_is_not_in_a_cited_result() -> None:
    """The zero baseline is drawn by the renderer; it is not an annotation citing a result."""
    spec = render(MARCH, contract_example_catalog())
    assert spec.annotations == []


def test_every_plotted_value_comes_from_a_cited_result() -> None:
    catalog = FakeSeriesCatalog()
    spec = render({"preset": "last_6_months"}, catalog)
    expected = FakeSeriesCatalog().cash_flow(date(2026, 4, 1), date(2026, 10, 1), "USD")

    assert expected.rows is not None
    assert points(spec, "inflow") == [(r.month.isoformat(), r.inflow) for r in expected.rows]
    assert points(spec, "outflow") == [(r.month.isoformat(), r.outflow) for r in expected.rows]
    assert points(spec, "net") == [(r.month.isoformat(), r.net) for r in expected.rows]
    cited = {s.result_id for s in spec.series}
    assert cited == {s.result_id for s in spec.sources}


def test_running_net_comes_from_the_engine_and_reconciles_to_the_total() -> None:
    spec = render({"preset": "last_6_months"})
    expected = FakeSeriesCatalog().cash_flow(date(2026, 4, 1), date(2026, 10, 1), "USD")
    running = next(s for s in spec.series if s.id == "running_net")

    assert running.result_id.startswith("running_net:res_fake_")
    assert running.points[-1].y == expected.totals["net"]
    assert {s.query for s in spec.sources} == {"cash_flow", "running_net"}


def test_title_states_the_finding_from_the_catalog_total() -> None:
    expected = FakeSeriesCatalog().cash_flow(date(2026, 4, 1), date(2026, 10, 1), "USD")
    spec = render({"preset": "last_6_months"})

    assert spec.title == (
        f"You earned more than you spent, Apr 2026 – Sep 2026: net ${expected.totals['net']:,}"
    )


def test_no_data_gives_a_neutral_title_no_series_and_no_running_source() -> None:
    spec = render({"preset": "custom", "start": "2020-01-01", "end": "2020-02-01"})

    assert spec.title == "Cash flow, Jan 1, 2020 – Jan 31, 2020"
    assert spec.series == [] and spec.annotations == [] and spec.table.rows == []
    assert [s.query for s in spec.sources] == ["cash_flow"]


def test_currency_is_passed_through_and_never_mixed() -> None:
    spec = render(MARCH, currency="EUR")

    assert points(spec, "outflow") == [("2026-03-01", Decimal("30.00"))]
    assert spec.table.rows[0][2] == "€30.00"
    assert spec.params["currency"] == "EUR"


def test_balanced_month_has_a_neutral_finding() -> None:
    catalog = FakeSeriesCatalog(
        [
            SyntheticTransaction(date(2026, 3, 1), Decimal("100.00"), "income"),
            SyntheticTransaction(date(2026, 3, 2), Decimal("-100.00"), "rent"),
        ]
    )
    assert render(MARCH, catalog).title == "Income and spending matched, Mar 2026"


def test_unknown_params_and_bad_periods_are_rejected() -> None:
    with pytest.raises(ValidationError):
        render(MARCH, interval="weekly")
    with pytest.raises(ValidationError):
        render({"preset": "custom"})


def test_served_over_http_with_string_money() -> None:
    app = create_app(default_registry(), contract_example_catalog, lambda: TODAY)
    response = TestClient(app).post(
        "/charts/render", json={"template_id": "cash_flow", "params": {"period": MARCH}}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["series"][2]["points"][0]["y"] == "-210.75"
    assert body["title"] == "You spent more than you earned, Mar 2026: net −$210.75"
