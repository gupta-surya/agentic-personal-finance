"""``category_trends``: "What's growing in my spending?"

A table of categories with a sparkline and a rising / falling / flat badge. The monthly
series, averages, extremes and directions all come from the ``category_trends`` engine
(which cites the spend query it read); the builder only selects, labels and formats.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from finance_agent.charts.period import last_n_months, months_of
from finance_agent.charts.registry import Template
from finance_agent.charts.spec import Assumption, ChartSpec, Point, Series, Table
from finance_agent.charts.templates.common import (
    category_label,
    format_change,
    format_money,
    series_id,
    source_of,
    span_label,
)
from finance_agent.engines.category_trends import FLAT_BAND, MIN_MONTHS, category_trends
from finance_agent.queries.series import SeriesCatalog

_BADGE = {
    "rising": "▲ Rising",
    "falling": "▼ Falling",
    "flat": "– Flat",
    "insufficient_data": "Not enough data",
}


class CategoryTrendsParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: Literal["category_trends"]
    months: int = Field(default=6, ge=3, le=12)  # complete months before this one
    categories: list[str] = []  # explicit selection; empty means the top N
    top_n: int = Field(default=6, ge=1, le=12)
    currency: str = "USD"


def build(params: CategoryTrendsParams, catalog: SeriesCatalog, today: date) -> ChartSpec:
    period = last_n_months(today, params.months)
    months = months_of(period)
    chosen = set(params.categories)
    spend = catalog.monthly_spend_by_category(
        period.start, period.end, params.currency, top_n=None if chosen else params.top_n
    )
    if spend.rows is None:
        raise ValueError("monthly_spend_by_category must return rows")
    # The engine applies the selection and records it, so the figures cite this exact result.
    trends = category_trends(spend, months, only=chosen or None)
    assert trends.rows is not None

    cur = params.currency
    labels = [category_label(r.category, is_other=r.is_other) for r in trends.rows]
    span = span_label(months[0], months[-1])
    assumptions = [
        Assumption(key="currency", label="Currency", value=cur, source="default"),
        Assumption(
            key="window",
            label="Window",
            value=f"{params.months} complete months, {span}",
            source="default",
        ),
        Assumption(
            key="rule",
            label="Direction",
            value=(
                "Compares the last half of the window with the first half: "
                f"{FLAT_BAND:.0%} or more is rising or falling, less is flat. "
                f"Needs at least {MIN_MONTHS} months."
            ),
            source="default",
        ),
    ]
    if chosen:
        names = ", ".join(category_label(c) for c in sorted(chosen))
        assumptions.append(
            Assumption(key="categories", label="Categories", value=names, source="question")
        )

    return ChartSpec(
        template_id="category_trends",
        title=f"Category spending trends, {span}",
        params=params.model_dump(mode="json"),
        period=period,
        series=[
            Series(
                id=series_id(r.category, r.is_other),
                kind="line",
                label=label,
                result_id=trends.result_id,
                points=[
                    Point(x=m.isoformat(), y=v) for m, v in zip(months, r.monthly, strict=True)
                ],
            )
            for r, label in zip(trends.rows, labels, strict=True)
        ],
        assumptions=assumptions,
        sources=[source_of(spend), source_of(trends)] if trends.rows else [source_of(spend)],
        table=Table(
            columns=[
                "Category",
                "Average per month",
                "Lowest month",
                "Highest month",
                "Change",
                "Trend",
            ],
            rows=[
                [
                    label,
                    format_money(r.average, cur),
                    format_money(r.minimum, cur),
                    format_money(r.maximum, cur),
                    format_change(r.change),
                    _BADGE[r.direction],
                ]
                for r, label in zip(trends.rows, labels, strict=True)
            ],
        ),
    )


TEMPLATE = Template("category_trends", CategoryTrendsParams, build)
