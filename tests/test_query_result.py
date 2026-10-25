from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from finance_agent.db.loader import Connection
from finance_agent.queries.result import CashFlowRow, MonthlyCategorySpendRow, QueryResult
from finance_agent.queries.series import CashFlow, MonthlySpendByCategory


def _result(**overrides: object) -> QueryResult[MonthlyCategorySpendRow]:
    fields: dict[str, object] = {
        "query": "monthly_spend_by_category",
        "params": {"start": "2026-03-01", "end": "2026-05-01", "currency": "USD"},
        "result_id": "r-1",
        "data_version": "v1",
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


def test_protocols_are_satisfiable_by_plain_functions() -> None:
    """mypy checks these assignments: a plain function matching the signature fits."""

    def spend(
        conn: Connection, tenant_id: str, start: date, end: date, currency: str
    ) -> QueryResult[MonthlyCategorySpendRow]:
        return _result(rows=[])

    def flow(
        conn: Connection, tenant_id: str, start: date, end: date, currency: str
    ) -> QueryResult[CashFlowRow]:
        return QueryResult[CashFlowRow](
            query="cash_flow", params={}, result_id="r-4", data_version="v1", rows=[]
        )

    spend_query: MonthlySpendByCategory = spend
    flow_query: CashFlow = flow

    assert callable(spend_query) and callable(flow_query)
