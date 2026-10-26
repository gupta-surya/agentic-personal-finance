import json

from finance_agent.charts.contract_export import (
    OPENAPI_FILE,
    SCHEMA_FILE,
    openapi,
    render,
    render_openapi,
)
from finance_agent.queries.contract_export import CONTRACTS_DIR


def test_committed_chart_spec_schema_matches_the_python_types() -> None:
    assert (CONTRACTS_DIR / SCHEMA_FILE).read_text(encoding="utf-8") == render(), (
        f"{SCHEMA_FILE} is stale: run `python -m finance_agent.charts.contract_export`"
    )


def test_committed_openapi_matches_the_api() -> None:
    assert (CONTRACTS_DIR / OPENAPI_FILE).read_text(encoding="utf-8") == render_openapi(), (
        f"{OPENAPI_FILE} is stale: run `python -m finance_agent.charts.contract_export`"
    )


def test_money_is_a_string_in_the_schema() -> None:
    point = json.loads(render())["$defs"]["Point"]["properties"]
    for name in ("y", "low", "high"):
        assert {"type": "string"} in point[name]["anyOf"]
        assert not any(branch.get("type") == "number" for branch in point[name]["anyOf"])


def test_openapi_describes_the_render_route_and_string_money() -> None:
    doc = openapi()
    assert "/charts/render" in doc["paths"]
    point = doc["components"]["schemas"]["Point"]["properties"]["y"]
    assert {"type": "string"} in point["anyOf"]
