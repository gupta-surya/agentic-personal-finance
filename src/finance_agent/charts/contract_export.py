"""Generate the ChartSpec JSON Schema the frontend types are built from.

``python -m finance_agent.charts.contract_export`` rewrites
``contracts/chart_spec.schema.json``; a test fails if the committed file differs, so
the frontend cannot drift from the Python types. Money fields are JSON strings.
"""

import json
from typing import Any

from finance_agent.charts.spec import ChartSpec
from finance_agent.queries.contract_export import CONTRACTS_DIR

FILE_NAME = "chart_spec.schema.json"


def schema() -> dict[str, Any]:
    return ChartSpec.model_json_schema(mode="serialization")


def render() -> str:
    return json.dumps(schema(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    CONTRACTS_DIR.mkdir(exist_ok=True)
    (CONTRACTS_DIR / FILE_NAME).write_text(render(), encoding="utf-8")


if __name__ == "__main__":
    main()
