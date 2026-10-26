from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from finance_agent.queries.result import (
    AMOUNTS_IN_DECIMAL,
    CashFlowRow,
    MonthlyCategorySpendRow,
    QueryResult,
    ScalarRow,
    SpendBreakdownRow,
)
from finance_agent.queries.series import SeriesCatalog

AS_OF = datetime(2026, 4, 2, 12, 0, tzinfo=UTC)


def _result(**overrides: object) -> QueryResult[MonthlyCategorySpendRow]:
    fields: dict[str, object] = {
        "query": "monthly_spend_by_category",
        "params": {"start": "2026-03-01", "end": "2026-05-01", "currency": "USD"},
        "result_id": "r-1",
        "data_version": "v1",
        "as_of": AS_OF,
        "amounts_in": AMOUNTS_IN_DECIMAL,
        "rows": [
            MonthlyCategorySpendRow(
                month=date(2026, 3, 1), category="groceries", spend=Decimal("285.32")
            )
        ],
    }
    fields.update(overrides)
    return QueryResult[MonthlyCategorySpendRow].model_validate(fields)


def test_rows_result_round_trips_through_json_with_exact_decimals() -> None:
    result = _result()

    payload = result.model_dump_json()
    restored = QueryResult[MonthlyCategorySpendRow].model_validate_json(payload)

    assert '"spend":"285.32"' in payload  # a string, so no float rounding in the browser
    assert restored == result
    assert restored.rows is not None
    assert restored.rows[0].spend == Decimal("285.32")


def test_scalar_value_result() -> None:
    result = QueryResult[MonthlyCategorySpendRow](
        query="spend_by_category",
        params={"category": "groceries"},
        result_id="r-2",
        data_version="v1",
        as_of=AS_OF,
        amounts_in=AMOUNTS_IN_DECIMAL,
        value=Decimal("285.32"),
    )

    assert result.value == Decimal("285.32")
    assert result.rows is None


def test_empty_rows_is_valid_and_distinct_from_zero_value() -> None:
    empty = _result(rows=[])
    zero = QueryResult[MonthlyCategorySpendRow](
        query="spend_by_category",
        params={},
        result_id="r-3",
        data_version="v1",
        as_of=AS_OF,
        amounts_in=AMOUNTS_IN_DECIMAL,
        value=Decimal("0"),
    )

    assert empty.rows == []
    assert empty.value is None
    assert zero.value == Decimal("0")
    assert zero.rows is None


def test_value_and_rows_together_are_rejected() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        _result(value=Decimal("1"))


def test_neither_value_nor_rows_is_rejected() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        _result(rows=None)


def test_float_money_is_rejected() -> None:
    with pytest.raises(ValidationError, match="never a float"):
        MonthlyCategorySpendRow(month=date(2026, 3, 1), category="groceries", spend=285.32)
    with pytest.raises(ValidationError, match="never a float"):
        _result(rows=None, value=285.32)


def test_uncategorized_row_is_allowed() -> None:
    row = MonthlyCategorySpendRow(month=date(2026, 3, 1), category=None, spend=Decimal("1.00"))

    assert row.category is None


def test_result_is_immutable() -> None:
    result = _result()

    with pytest.raises(ValidationError):
        result.result_id = "other"  # type: ignore[misc]


def test_month_must_be_first_day_on_both_row_types() -> None:
    with pytest.raises(ValidationError, match="first day of a month"):
        MonthlyCategorySpendRow(month=date(2026, 3, 15), category="groceries", spend=Decimal("1"))
    with pytest.raises(ValidationError, match="first day of a month"):
        CashFlowRow(
            month=date(2026, 3, 31),
            inflow=Decimal("10"),
            outflow=Decimal("4"),
            net=Decimal("6"),
        )


def test_cash_flow_net_must_equal_inflow_minus_outflow() -> None:
    with pytest.raises(ValidationError, match="net must equal inflow - outflow"):
        CashFlowRow(
            month=date(2026, 3, 1),
            inflow=Decimal("3200.00"),
            outflow=Decimal("2000.00"),
            net=Decimal("1200.01"),
        )


def test_cash_flow_allows_negative_net() -> None:
    row = CashFlowRow(
        month=date(2026, 3, 1),
        inflow=Decimal("100.00"),
        outflow=Decimal("250.50"),
        net=Decimal("-150.50"),
    )

    assert row.net == Decimal("-150.50")


class _StubCatalog:
    """Constructed like the real one would be, minus the database."""

    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id

    def monthly_spend_by_category(
        self, start: date, end: date, currency: str, top_n: int | None = None
    ) -> QueryResult[MonthlyCategorySpendRow]:
        return _result(rows=[])

    def spend_breakdown(
        self,
        start: date,
        end: date,
        currency: str,
        group_by: Literal["category"] = "category",
        top_n: int | None = None,
    ) -> QueryResult[SpendBreakdownRow]:
        raise NotImplementedError

    def kpi(
        self,
        measure: Literal["spend", "income", "net"],
        start: date,
        end: date,
        currency: str,
        category: str | None = None,
    ) -> QueryResult[ScalarRow]:
        raise NotImplementedError

    def cash_flow(self, start: date, end: date, currency: str) -> QueryResult[CashFlowRow]:
        return QueryResult[CashFlowRow](
            query="cash_flow",
            params={},
            result_id="r-4",
            data_version="v1",
            as_of=AS_OF,
            amounts_in=AMOUNTS_IN_DECIMAL,
            rows=[],
        )


def test_series_catalog_is_satisfiable_by_a_plain_class() -> None:
    """mypy checks the assignment: a class with these methods fits the Protocol."""
    catalog: SeriesCatalog = _StubCatalog("demo-tenant")

    assert catalog.cash_flow(date(2026, 3, 1), date(2026, 4, 1), "USD").rows == []


def test_series_contract_does_not_import_the_database_layer() -> None:
    import ast

    import finance_agent.queries.result as result_module
    import finance_agent.queries.series as series_module

    for module in (result_module, series_module):
        tree = ast.parse(Path(module.__file__ or "").read_text(encoding="utf-8"))
        imported = [
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        ] + [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        assert not [name for name in imported if name.startswith("finance_agent.db")]


def test_as_of_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        _result(as_of=datetime(2026, 4, 2, 12, 0))


def test_totals_are_exact_decimals_and_default_to_empty() -> None:
    assert _result().totals == {}

    result = _result(totals={"spend": Decimal("285.32")})

    assert result.model_dump_json().count('"totals":{"spend":"285.32"}') == 1
    with pytest.raises(ValidationError, match="never a float"):
        _result(totals={"spend": 285.32})


def test_envelope_states_its_units_and_data_age() -> None:
    result = _result()

    assert result.amounts_in == AMOUNTS_IN_DECIMAL
    assert '"as_of":"2026-04-02T12:00:00Z"' in result.model_dump_json()
