import time
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from finance_agent.charts.api import create_app
from finance_agent.charts.fake_catalog import FakeSeriesCatalog
from finance_agent.charts.period import Period, PeriodPreset, resolve_period
from finance_agent.charts.registry import TemplateRegistry
from finance_agent.charts.spec import enforce_point_budget
from tests.charts.test_spec_registry import registry

TODAY = date(2026, 10, 25)


def make_client(reg: TemplateRegistry | None = None) -> TestClient:
    app = create_app(reg or registry(), FakeSeriesCatalog, lambda: TODAY)
    return TestClient(app)


def post(client: TestClient, template_id: str = "echo", **params: Any) -> Any:
    return client.post("/charts/render", json={"template_id": template_id, "params": params})


def test_render_returns_a_chart_spec_with_money_as_strings() -> None:
    response = post(make_client(), period={"preset": "last_3_months"})

    assert response.status_code == 200
    body = response.json()
    assert body["template_id"] == "echo"
    assert all(isinstance(p["y"], str) for p in body["series"][0]["points"])


def test_same_request_and_pinned_today_is_identical() -> None:
    first = post(make_client(), period={"preset": "last_6_months"})
    second = post(make_client(), period={"preset": "last_6_months"})
    assert first.content == second.content


def test_response_period_matches_the_resolver() -> None:
    body = post(make_client(), period={"preset": "year_to_date"}).json()
    resolved = resolve_period(Period(preset=PeriodPreset.YEAR_TO_DATE), TODAY)
    assert body["period"]["start"] == resolved.start.isoformat()
    assert body["period"]["end"] == resolved.end.isoformat()


def test_unknown_template_is_404() -> None:
    response = post(make_client(), "nope")
    assert response.status_code == 404


def test_bad_params_are_422_with_field_paths() -> None:
    response = post(make_client(), period={"preset": "last_decade"})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][:2] == ["params", "period"]


def test_custom_period_without_dates_is_422_not_500() -> None:
    assert post(make_client(), period={"preset": "custom"}).status_code == 422


def test_conflicting_template_in_params_is_422() -> None:
    response = post(make_client(), template="other", period={"preset": "last_month"})
    assert response.status_code == 422


def test_unknown_request_fields_are_rejected() -> None:
    response = make_client().post("/charts/render", json={"template_id": "echo", "extra": 1})
    assert response.status_code == 422


def test_point_budget_exceeded_is_422(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "finance_agent.charts.registry.enforce_point_budget",
        lambda spec: enforce_point_budget(spec, limit=2),
    )
    response = post(make_client(), period={"preset": "last_12_months"})
    assert response.status_code == 422
    assert "points" in response.json()["detail"]


def test_render_is_fast_on_fake_data() -> None:
    client = make_client()
    started = time.perf_counter()
    for _ in range(10):
        assert post(client, period={"preset": "last_12_months"}).status_code == 200
    assert (time.perf_counter() - started) / 10 < 0.5  # generous; real target is < 80 ms
