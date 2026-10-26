"""Cumulative net cash flow across the months of a ``cash_flow`` result."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from finance_agent.queries.result import CashFlowRow, Money, QueryResult


class RunningNetRow(BaseModel):
    """``running_net`` is the sum of ``net`` from the first month through ``month``."""

    model_config = ConfigDict(frozen=True)

    month: date  # first day of the month
    running_net: Money


def running_net(source: QueryResult[CashFlowRow]) -> QueryResult[RunningNetRow]:
    """Running total of the source's monthly ``net``, in the source's month order.

    The result id is derived from the source's (``running_net:<source id>``), so one
    source execution yields one engine result and the dependency is visible in the id.
    ``totals["running_net"]`` equals the source's ``totals["net"]`` by construction.
    """
    if source.rows is None:
        raise ValueError("running_net needs a cash_flow result with rows")
    total = Decimal(0)
    rows: list[RunningNetRow] = []
    for row in source.rows:
        total += row.net
        rows.append(RunningNetRow(month=row.month, running_net=total))
    return QueryResult[RunningNetRow](
        query="running_net",
        params={**source.params, "source_result_id": source.result_id},
        result_id=f"running_net:{source.result_id}",
        data_version=source.data_version,
        as_of=source.as_of,
        amounts_in=source.amounts_in,
        rows=rows,
        totals={"running_net": total} if rows else {},
    )
