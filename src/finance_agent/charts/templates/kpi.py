"""``kpi``: "How much did I spend on dining last month?"

One headline number with its change from the calendar-aligned previous period (``previous_of``). The
value and the previous value are two scalar ``kpi`` queries; the change amount and
percentage come from the ``period_delta`` engine, which cites both. The builder only
copies and labels them.

The change is shown only when the data covers the whole previous period. If history
starts inside it (twelve months asked of thirteen months of data, or ``all_time``), the
previous total would be a few days or weeks of spending, and comparing a year with that
is not a change, so the tile shows the value with "not enough history" instead.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from finance_agent.charts.period import (
    Period,
    ResolvedPeriod,
    comparison_label,
    day_label,
    previous_of,
    range_label,
)
from finance_agent.charts.registry import Template
from finance_agent.charts.spec import Assumption, ChartSpec, Point, Series, Table
from finance_agent.charts.templates.common import (
    category_label,
    format_money,
    format_share,
    resolve,
    source_of,
    span_label,
)
from finance_agent.engines.period_delta import period_delta
from finance_agent.queries.result import QueryResult, ScalarRow
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


NOT_ENOUGH_HISTORY = "Not enough history"


def _history_start(catalog: SeriesCatalog, currency: str) -> tuple[bool, date | None]:
    """``(known, first date with data in this currency)``. Both catalogs report their
    first posted date (a method outside the ``SeriesCatalog`` protocol, as for
    ``all_time``); a catalog that cannot say keeps the comparison, as before."""
    earliest = getattr(catalog, "earliest_date", None)
    if earliest is None:
        return False, None
    first: date | None = earliest(currency)
    return True, first


def _covers(previous_start: date, catalog: SeriesCatalog, currency: str) -> tuple[bool, str | None]:
    """Whether the data covers the whole previous period, and if not, why (for the
    "Compared with" line). History is per currency: a EUR account opened later has a
    shorter history than the USD ones."""
    known, first = _history_start(catalog, currency)
    if not known:
        return True, None
    if first is None:
        return False, f"{NOT_ENOUGH_HISTORY}: there is no {currency} data yet"
    if previous_start < first:
        return False, f"{NOT_ENOUGH_HISTORY}: your {currency} data starts {day_label(first)}"
    return True, None


def build(params: KpiParams, catalog: SeriesCatalog, today: date) -> ChartSpec:
    period = resolve(params.period, today, catalog)
    prior = previous_of(period)
    current = catalog.kpi(
        params.measure, period.start, period.end, params.currency, category=params.category
    )
    if current.value is None:
        raise ValueError("kpi must return scalar values")
    if prior is None:  # all_time: nothing precedes it
        return _without_comparison(params, period, current, NOT_ENOUGH_HISTORY, NOT_ENOUGH_HISTORY)
    previous_label = range_label(prior.start, prior.end)
    comparable, reason = _covers(prior.start, catalog, params.currency)
    if not comparable:
        assert reason is not None
        return _without_comparison(params, period, current, previous_label, reason)
    previous = catalog.kpi(
        params.measure, prior.start, prior.end, params.currency, category=params.category
    )
    delta = period_delta(current, previous)
    if previous.value is None or delta.rows is None:
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

    return ChartSpec(
        template_id="kpi",
        title=_title(params, current.value, span),
        params=params.model_dump(mode="json"),
        period=period,
        series=series,
        assumptions=_assumptions(params, comparison_label(prior)),
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


def _assumptions(params: KpiParams, compared_with: str) -> list[Assumption]:
    assumptions = [
        Assumption(key="currency", label="Currency", value=params.currency, source="default"),
        Assumption(
            key="measure", label="Measure", value=_MEASURE_NAME[params.measure], source="question"
        ),
        Assumption(
            key="compared_with", label="Compared with", value=compared_with, source="default"
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
    return assumptions


def _without_comparison(
    params: KpiParams,
    period: ResolvedPeriod,
    current: QueryResult[ScalarRow],
    previous_label: str,
    reason: str,
) -> ChartSpec:
    """The value alone. The previous period is not queried at all: a partial total is not
    a figure worth citing. The table keeps its four rows so readers find the same shape."""
    assert current.value is not None
    cur = params.currency
    span = span_label(period.start, period.end - timedelta(days=1))
    return ChartSpec(
        template_id="kpi",
        title=_title(params, current.value, span),
        params=params.model_dump(mode="json"),
        period=period,
        series=[
            Series(
                id="current",
                kind="point",
                label=period.label,
                result_id=current.result_id,
                points=[Point(x=period.label, y=current.value)],
            )
        ],
        assumptions=_assumptions(params, reason),
        sources=[source_of(current)],
        table=Table(
            columns=["Measure", "Value"],
            rows=[
                [period.label, format_money(current.value, cur)],
                [f"Previous period, {previous_label}", NOT_ENOUGH_HISTORY],
                ["Change", "n/a"],
                ["Change, percent", "n/a"],
            ],
        ),
    )


TEMPLATE = Template("kpi", KpiParams, build)
