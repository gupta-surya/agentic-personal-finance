"""Generate the frontend contract: JSON Schemas and example payloads for series results.

``python -m finance_agent.queries.contract_export`` rewrites ``contracts/``. A test
fails if the committed files differ from what this module generates, so the files
the frontend reads cannot drift from the Python types.

Money (``spend``, ``inflow``, ``outflow``, ``net``) is a JSON *string* holding an
exact decimal, e.g. ``"285.32"``. Parse it with a decimal library, not a float.
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from finance_agent.queries.result import CashFlowRow, MonthlyCategorySpendRow, QueryResult

CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"

_PARAMS: dict[str, Any] = {"start": "2026-02-01", "end": "2026-04-01", "currency": "USD"}


def schemas() -> dict[str, dict[str, Any]]:
    return {
        "monthly_spend_by_category.schema.json": QueryResult[
            MonthlyCategorySpendRow
        ].model_json_schema(mode="serialization"),
        "cash_flow.schema.json": QueryResult[CashFlowRow].model_json_schema(mode="serialization"),
    }


def examples() -> dict[str, dict[str, Any]]:
    spend = QueryResult[MonthlyCategorySpendRow](
        query="monthly_spend_by_category",
        params=_PARAMS,
        result_id="res_7f3a",
        data_version="dv_12",
        rows=[
            MonthlyCategorySpendRow(
                month=date(2026, 2, 1), category="groceries", spend=Decimal("412.18")
            ),
            MonthlyCategorySpendRow(
                month=date(2026, 3, 1), category="groceries", spend=Decimal("285.32")
            ),
            MonthlyCategorySpendRow(month=date(2026, 3, 1), category=None, spend=Decimal("19.99")),
        ],
    )
    flow = QueryResult[CashFlowRow](
        query="cash_flow",
        params=_PARAMS,
        result_id="res_7f3b",
        data_version="dv_12",
        rows=[
            CashFlowRow(
                month=date(2026, 2, 1),
                inflow=Decimal("3200.00"),
                outflow=Decimal("2650.40"),
                net=Decimal("549.60"),
            ),
            CashFlowRow(
                month=date(2026, 3, 1),
                inflow=Decimal("3200.00"),
                outflow=Decimal("3410.75"),
                net=Decimal("-210.75"),
            ),
        ],
    )
    return {
        "monthly_spend_by_category.example.json": spend.model_dump(mode="json"),
        "cash_flow.example.json": flow.model_dump(mode="json"),
    }


def render() -> dict[str, str]:
    """File name -> exact file text, for both schemas and examples."""
    files = {**schemas(), **examples()}
    return {name: json.dumps(doc, indent=2, sort_keys=True) + "\n" for name, doc in files.items()}


def main() -> None:
    CONTRACTS_DIR.mkdir(exist_ok=True)
    for name, text in render().items():
        (CONTRACTS_DIR / name).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
