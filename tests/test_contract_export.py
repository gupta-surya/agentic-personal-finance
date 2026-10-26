import json

from pydantic import TypeAdapter

from finance_agent.queries.contract_export import CONTRACTS_DIR, examples, render
from finance_agent.queries.result import CashFlowRow, MonthlyCategorySpendRow, QueryResult


def test_committed_contract_files_match_the_python_types() -> None:
    for name, text in render().items():
        assert (CONTRACTS_DIR / name).read_text(encoding="utf-8") == text, (
            f"{name} is stale: run `python -m finance_agent.queries.contract_export`"
        )


def test_examples_validate_against_the_models() -> None:
    docs = examples()

    spend = QueryResult[MonthlyCategorySpendRow].model_validate(
        docs["monthly_spend_by_category.example.json"]
    )
    flow = QueryResult[CashFlowRow].model_validate(docs["cash_flow.example.json"])

    assert spend.rows is not None and flow.rows is not None
    assert flow.rows[1].net == flow.rows[1].inflow - flow.rows[1].outflow


def test_money_is_a_string_in_the_schema_and_the_examples() -> None:
    schema = json.loads((CONTRACTS_DIR / "cash_flow.schema.json").read_text(encoding="utf-8"))
    net = schema["$defs"]["CashFlowRow"]["properties"]["net"]
    example = json.loads((CONTRACTS_DIR / "cash_flow.example.json").read_text(encoding="utf-8"))

    assert net["type"] == "string"
    assert example["rows"][1]["net"] == "-210.75"
    assert TypeAdapter(str).validate_python(example["rows"][0]["inflow"]) == "3200.00"
