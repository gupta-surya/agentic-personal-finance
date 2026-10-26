"""Generate the frontend contracts for charts: the ChartSpec JSON Schema and the
OpenAPI document, from which the TypeScript types are built.

``python -m finance_agent.charts.contract_export`` rewrites both files in
``contracts/``; a test fails if either differs from what this module generates, so
the frontend cannot drift from the Python types. Money fields are JSON strings.
"""

import json
from datetime import date
from typing import Any

from finance_agent.charts.api import create_app
from finance_agent.charts.fake_catalog import FakeSeriesCatalog
from finance_agent.charts.registry import TemplateRegistry
from finance_agent.charts.spec import ChartSpec
from finance_agent.queries.contract_export import CONTRACTS_DIR

SCHEMA_FILE = "chart_spec.schema.json"
OPENAPI_FILE = "charts.openapi.json"


def schema() -> dict[str, Any]:
    return ChartSpec.model_json_schema(mode="serialization")


def openapi() -> dict[str, Any]:
    app = create_app(TemplateRegistry(), FakeSeriesCatalog, lambda: date(2026, 1, 1))
    return app.openapi()


def render() -> str:
    return json.dumps(schema(), indent=2, sort_keys=True) + "\n"


def render_openapi() -> str:
    return json.dumps(openapi(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    CONTRACTS_DIR.mkdir(exist_ok=True)
    (CONTRACTS_DIR / SCHEMA_FILE).write_text(render(), encoding="utf-8")
    (CONTRACTS_DIR / OPENAPI_FILE).write_text(render_openapi(), encoding="utf-8")


if __name__ == "__main__":
    main()
