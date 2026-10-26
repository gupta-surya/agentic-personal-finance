"""``cash_flow``: "Am I spending more than I earn?"

Inflow and outflow bars and a net line, copied from ``cash_flow`` rows; a running net
from the ``running_net`` engine. The title states a finding using only figures the
catalog returned (``totals["net"]``), never a number computed here.
"""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from finance_agent.charts.period import Period, resolve_period
from finance_agent.charts.registry import Template
from finance_agent.charts.spec import Assumption, ChartSpec, Point, Series, Table
from finance_agent.charts.templates.common import (
    format_money,
    month_label,
    source_of,
    span_label,
)
from finance_agent.engines.running_net import running_net
from finance_agent.queries.series import SeriesCatalog


class CashFlowParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: Literal["cash_flow"]
    period: Period
    currency: str = "USD"


def _title(net: Decimal | None, span: str, currency: str) -> str:
    if net is None:
        return f"Cash flow, {span}"
    # The net is quoted exactly as the catalog returned it; no figure is derived here.
    if net < 0:
        return f"You spent more than you earned, {span}: net {format_money(net, currency)}"
    if net > 0:
        return f"You earned more than you spent, {span}: net {format_money(net, currency)}"
    return f"Income and spending matched, {span}"


def build(params: CashFlowParams, catalog: SeriesCatalog, today: date) -> ChartSpec:
    period = resolve_period(params.period, today)
    result = catalog.cash_flow(period.start, period.end, params.currency)
    if result.rows is None:
        raise ValueError("cash_flow must return rows")
    rows = result.rows
    running = running_net(result)
    assert running.rows is not None  # same rows as the source

    cur = params.currency
    span = span_label(rows[0].month, rows[-1].month) if rows else period.label
    series: list[Series] = []
    if rows:
        series = [
            Series(
                id="inflow",
                kind="bar",
                label="Inflow",
                result_id=result.result_id,
                points=[Point(x=r.month.isoformat(), y=r.inflow) for r in rows],
            ),
            Series(
                id="outflow",
                kind="bar",
                label="Outflow",
                result_id=result.result_id,
                points=[Point(x=r.month.isoformat(), y=r.outflow) for r in rows],
            ),
            Series(
                id="net",
                kind="line",
                label="Net",
                result_id=result.result_id,
                points=[Point(x=r.month.isoformat(), y=r.net) for r in rows],
            ),
            Series(
                id="running_net",
                kind="line",
                label="Running net",
                result_id=running.result_id,
                points=[Point(x=r.month.isoformat(), y=r.running_net) for r in running.rows],
            ),
        ]

    return ChartSpec(
        template_id="cash_flow",
        title=_title(result.totals.get("net"), span, cur),
        params=params.model_dump(mode="json"),
        period=period,
        series=series,
        assumptions=[
            Assumption(key="currency", label="Currency", value=cur, source="default"),
            Assumption(key="interval", label="Interval", value="Monthly", source="default"),
        ],
        sources=[source_of(result), source_of(running)] if rows else [source_of(result)],
        table=Table(
            columns=["Month", "Inflow", "Outflow", "Net", "Running net"],
            rows=[
                [
                    month_label(r.month),
                    format_money(r.inflow, cur),
                    format_money(r.outflow, cur),
                    format_money(r.net, cur),
                    format_money(run.running_net, cur),
                ]
                for r, run in zip(rows, running.rows, strict=True)
            ],
        ),
    )


TEMPLATE = Template("cash_flow", CashFlowParams, build)
