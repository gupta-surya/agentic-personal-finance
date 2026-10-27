"""``kpi``: "How much did I spend on dining last month?"

One headline number with its change from the previous period of the same length. The
value and the previous value are two scalar ``kpi`` queries; the change amount and
percentage come from the ``period_delta`` engine, which cites both. The builder only
copies and labels them.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from finance_agent.charts.period import Period, range_label, resolve_period
from finance_agent.charts.registry import Template
from finance_agent.charts.spec import Assumption, ChartSpec, Point, Series, Table
from finance_agent.charts.templates.common import (
    category_label,
    format_money,
    format_share,
    source_of,
    span_label,
)
from finance_agent.engines.period_delta import period_delta
from finance_agent.queries.series import KpiMeasure, SeriesCatalog

_MEASURE_NAME = {"spend": "Spending", "income": "Income", "net": "Net cash flow"}


class KpiParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: Literal["kpi"]
    measure: KpiMeasure = "spend"
    period: Period
    category: str | None = None
    currency: str = "USD"

    @model_validator(mode="after")
    def _category_only_narrows_spend(self) -> Self:
        if self.category is not None and self.measure != "spend":
            raise ValueError("category applies only to the spend measure")
        return self


def _title(params: KpiParams, value: Decimal, span: str) -> str:
    amount = format_money(value, params.currency)
    if params.measure == "income":
        return f"You earned {amount}, {span}"
    if params.measure == "net":
        return f"Net cash flow was {amount}, {span}"
    if params.category is not None:
        return f"You spent {amount} on {category_label(params.category)}, {span}"
    return f"You spent {amount}, {span}"


def _signed(text: str, positive: bool) -> str:
    return f"+{text}" if positive else text


def build(params: KpiParams, catalog: SeriesCatalog, today: date) -> ChartSpec:
    period = resolve_period(params.period, today)
    # The previous period is the same length immediately before this one.
    previous_start = period.start - (period.end - period.start)
    previous_label = range_label(previous_start, period.start)

    current = catalog.kpi(
        params.measure, period.start, period.end, params.currency, category=params.category
    )
    previous = catalog.kpi(
        params.measure, previous_start, period.start, params.currency, category=params.category
    )
    delta = period_delta(current, previous)
    if current.value is None or previous.value is None or delta.rows is None:
        raise ValueError("kpi must return scalar values")
    change = delta.rows[0]
    cur = params.currency

    span = span_label(period.start, period.end - timedelta(days=1))
    change_text = _signed(format_money(change.amount, cur), change.amount > 0)
    percent_text = (
        "n/a"
        if change.percent is None
        else _signed(format_share(change.percent), change.percent > 0)
    )

    series = [
        Series(
            id="current",
            kind="point",
            label=period.label,
            result_id=current.result_id,
            points=[Point(x=period.label, y=current.value)],
        ),
        Series(
            id="previous",
            kind="point",
            label=previous_label,
            result_id=previous.result_id,
            points=[Point(x=previous_label, y=previous.value)],
        ),
        Series(
            id="change",
            kind="point",
            label="Change",
            result_id=delta.result_id,
            points=[Point(x="change", y=change.amount)],
        ),
    ]
    if change.percent is not None:
        series.append(
            Series(
                id="change_percent",
                kind="point",
                label="Change, percent",
                result_id=delta.result_id,
                points=[Point(x="change", y=change.percent)],
            )
        )

    assumptions = [
        Assumption(key="currency", label="Currency", value=cur, source="default"),
        Assumption(
            key="measure", label="Measure", value=_MEASURE_NAME[params.measure], source="question"
        ),
        Assumption(
            key="compared_with", label="Compared with", value=previous_label, source="default"
        ),
    ]
    if params.category is not None:
        assumptions.insert(
            2,
            Assumption(
                key="category",
                label="Category",
                value=category_label(params.category),
                source="question",
            ),
        )

    return ChartSpec(
        template_id="kpi",
        title=_title(params, current.value, span),
        params=params.model_dump(mode="json"),
        period=period,
        series=series,
        assumptions=assumptions,
        sources=[source_of(current), source_of(previous), source_of(delta)],
        table=Table(
            columns=["Measure", "Value"],
            rows=[
                [period.label, format_money(current.value, cur)],
                [f"Previous period, {previous_label}", format_money(previous.value, cur)],
                ["Change", change_text],
                ["Change, percent", percent_text],
            ],
        ),
    )


TEMPLATE = Template("kpi", KpiParams, build)
