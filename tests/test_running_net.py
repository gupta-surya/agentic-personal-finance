from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from finance_agent.engines.running_net import running_net
from finance_agent.queries.result import AMOUNTS_IN_DECIMAL, CashFlowRow, QueryResult

AS_OF = datetime(2026, 4, 2, 12, 0, tzinfo=UTC)


def cash_flow(rows: list[CashFlowRow] | None) -> QueryResult[CashFlowRow]:
    return QueryResult[CashFlowRow](
        query="cash_flow",
        params={"start": "2026-02-01", "end": "2026-05-01", "currency": "USD"},
        result_id="res_1",
        data_version="dv_9",
        as_of=AS_OF,
        amounts_in=AMOUNTS_IN_DECIMAL,
        rows=rows,
        totals={},
        value=None if rows is not None else Decimal(1),
    )


def month(m: int, inflow: str, outflow: str, net: str) -> CashFlowRow:
    return CashFlowRow(
        month=date(2026, m, 1), inflow=Decimal(inflow), outflow=Decimal(outflow), net=Decimal(net)
    )


def test_running_total_is_cumulative_and_exact() -> None:
    source = cash_flow(
        [
            month(2, "3200.00", "2650.40", "549.60"),
            month(3, "3200.00", "3410.75", "-210.75"),
            month(4, "3200.00", "3199.99", "0.01"),
        ]
    )

    result = running_net(source)

    assert result.rows is not None
    assert [r.running_net for r in result.rows] == [
        Decimal("549.60"),
        Decimal("338.85"),
        Decimal("338.86"),
    ]
    assert [r.month for r in result.rows] == [date(2026, 2, 1), date(2026, 3, 1), date(2026, 4, 1)]
    assert result.totals == {"running_net": Decimal("338.86")}


def test_final_running_total_equals_the_sum_of_nets() -> None:
    rows = [month(2, "10.10", "0.00", "10.10"), month(3, "0.00", "20.20", "-20.20")]
    result = running_net(cash_flow(rows))

    assert result.rows is not None
    assert result.rows[-1].running_net == sum((r.net for r in rows), Decimal(0))


def test_result_names_its_source_and_inherits_freshness() -> None:
    result = running_net(cash_flow([month(2, "1.00", "0.00", "1.00")]))

    assert result.query == "running_net"
    assert result.result_id == "running_net:res_1"
    assert result.params["source_result_id"] == "res_1"
    assert result.params["currency"] == "USD"
    assert (result.data_version, result.as_of) == ("dv_9", AS_OF)


def test_empty_source_gives_empty_rows_and_no_totals() -> None:
    result = running_net(cash_flow([]))
    assert result.rows == []
    assert result.totals == {}


def test_a_scalar_source_is_rejected() -> None:
    with pytest.raises(ValueError, match="rows"):
        running_net(cash_flow(None))
