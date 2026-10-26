import json

from finance_agent.charts.contract_export import FILE_NAME, render
from finance_agent.queries.contract_export import CONTRACTS_DIR


def test_committed_chart_spec_schema_matches_the_python_types() -> None:
    assert (CONTRACTS_DIR / FILE_NAME).read_text(encoding="utf-8") == render(), (
        f"{FILE_NAME} is stale: run `python -m finance_agent.charts.contract_export`"
    )


def test_money_is_a_string_in_the_schema() -> None:
    point = json.loads(render())["$defs"]["Point"]["properties"]
    for name in ("y", "low", "high"):
        assert {"type": "string"} in point[name]["anyOf"]
        assert not any(branch.get("type") == "number" for branch in point[name]["anyOf"])
