from datetime import UTC, datetime
from decimal import Decimal

import pytest

from finance_agent.engines.period_delta import DeltaRow, period_delta
from finance_agent.queries.result import AMOUNTS_IN_DECIMAL, QueryResult, ScalarRow

AS_OF = datetime(2026, 4, 2, 12, 0, tzinfo=UTC)


def scalar(result_id: str, value: str | None, data_version: str = "dv_1") -> QueryResult[ScalarRow]:
    return QueryResult[ScalarRow](
        query="kpi",
        params={"measure": "spend"},
        result_id=result_id,
        data_version=data_version,
        as_of=AS_OF,
        amounts_in=AMOUNTS_IN_DECIMAL,
        value=None if value is None else Decimal(value),
        rows=[] if value is None else None,
    )


def delta(current: str, previous: str) -> DeltaRow:
    result = period_delta(scalar("c", current), scalar("p", previous))
    assert result.rows is not None
    return result.rows[0]


def test_increase_decrease_and_unchanged_are_exact() -> None:
    up = delta("366.20", "300.00")
    assert (up.amount, up.percent) == (Decimal("66.20"), Decimal("0.2207"))

    down = delta("100.00", "125.00")
    assert (down.amount, down.percent) == (Decimal("-25.00"), Decimal("-0.2000"))

    flat = delta("50.00", "50.00")
    assert (flat.amount, flat.percent) == (Decimal("0.00"), Decimal("0.0000"))


def test_a_zero_previous_value_has_no_percentage_never_infinity() -> None:
    row = delta("40.00", "0.00")
    assert (row.amount, row.percent) == (Decimal("40.00"), None)

    nothing = delta("0.00", "0.00")
    assert (nothing.amount, nothing.percent) == (Decimal("0.00"), None)


def test_a_negative_previous_value_uses_its_magnitude() -> None:
    # net cash flow went from -100.00 to -50.00: an improvement of 50.00, i.e. +50%
    row = delta("-50.00", "-100.00")
    assert (row.amount, row.percent) == (Decimal("50.00"), Decimal("0.5000"))


def test_the_result_names_both_sources() -> None:
    result = period_delta(scalar("res_a", "10.00"), scalar("res_b", "5.00", "dv_2"))

    assert result.query == "period_delta"
    assert result.result_id == "period_delta:res_a:res_b"
    assert result.params["current_result_id"] == "res_a"
    assert result.params["previous_result_id"] == "res_b"
    assert result.data_version == "dv_1+dv_2"


def test_rows_results_are_rejected() -> None:
    with pytest.raises(ValueError, match="scalar"):
        period_delta(scalar("c", None), scalar("p", "1.00"))
