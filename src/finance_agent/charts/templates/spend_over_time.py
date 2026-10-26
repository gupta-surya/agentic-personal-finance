"""``spend_over_time``: "How has grocery spending changed this year?"

One series per category, monthly. Values are copied from
``monthly_spend_by_category`` rows; the top-N fold into "Everything else" is done by
the catalog (``top_n``), never here. Months a category has no spend are simply absent
from its series; nothing is filled in.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from finance_agent.charts.period import Period, resolve_period
from finance_agent.charts.registry import Template
from finance_agent.charts.spec import Assumption, ChartSpec, Point, Series, Table
from finance_agent.charts.templates.common import (
    category_label,
    format_money,
    month_label,
    source_of,
    span_label,
)
from finance_agent.queries.result import MonthlyCategorySpendRow
from finance_agent.queries.series import SeriesCatalog


class SpendOverTimeParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: Literal["spend_over_time"]
    period: Period
    categories: list[str] = []  # explicit selection; empty means the top N
    top_n: int = Field(default=6, ge=1, le=12)
    currency: str = "USD"


def _key(row: MonthlyCategorySpendRow) -> tuple[str, str | None]:
    return ("other", None) if row.is_other else ("category", row.category)


def _series_id(key: tuple[str, str | None]) -> str:
    kind, name = key
    if kind == "other":
        return "everything_else"
    return "uncategorized" if name is None else f"category:{name}"


def _sort_key(key: tuple[str, str | None]) -> tuple[int, str]:
    """Alphabetical, with Uncategorized and the folded bucket last. Deliberately not by
    total spend: ranking by total would be arithmetic on money in the builder."""
    kind, name = key
    if kind == "other":
        return (2, "")
    return (1, "") if name is None else (0, name)


def build(params: SpendOverTimeParams, catalog: SeriesCatalog, today: date) -> ChartSpec:
    period = resolve_period(params.period, today)
    chosen = set(params.categories)
    result = catalog.monthly_spend_by_category(
        period.start,
        period.end,
        params.currency,
        top_n=None if chosen else params.top_n,
    )
    if result.rows is None:
        raise ValueError("monthly_spend_by_category must return rows")
    rows = [r for r in result.rows if r.category in chosen] if chosen else result.rows

    keys = sorted({_key(r) for r in rows}, key=_sort_key)
    kind = "line" if len(keys) <= 2 else "bar"
    series = [
        Series(
            id=_series_id(key),
            kind=kind,
            label=category_label(key[1], is_other=key[0] == "other"),
            result_id=result.result_id,
            points=[Point(x=r.month.isoformat(), y=r.spend) for r in rows if _key(r) == key],
        )
        for key in keys
    ]

    months = sorted({r.month for r in rows})
    span = span_label(months[0], months[-1]) if months else period.label
    if len(keys) == 1 and chosen:
        title = f"{series[0].label} spending, {span}"
    else:
        title = f"Spending by category, {span}"

    cur = params.currency
    assumptions = [
        Assumption(key="currency", label="Currency", value=cur, source="default"),
        Assumption(key="interval", label="Interval", value="Monthly", source="default"),
    ]
    if chosen:
        names = ", ".join(category_label(c) for c in sorted(chosen))
        assumptions.append(
            Assumption(key="categories", label="Categories", value=names, source="question")
        )
    else:
        assumptions.append(
            Assumption(
                key="top_n",
                label="Categories shown",
                value=f"Top {params.top_n}; the rest are grouped as Everything else",
                source="default",
            )
        )

    by_cell = {(_series_id(_key(r)), r.month): r.spend for r in rows}
    return ChartSpec(
        template_id="spend_over_time",
        title=title,
        params=params.model_dump(mode="json"),
        period=period,
        series=series,
        assumptions=assumptions,
        sources=[source_of(result)],
        table=Table(
            columns=["Month", *[s.label for s in series]],
            rows=[
                [
                    month_label(month),
                    *[
                        format_money(spend, cur)
                        if (spend := by_cell.get((s.id, month))) is not None
                        else None
                        for s in series
                    ],
                ]
                for month in months
            ],
        ),
    )


TEMPLATE = Template("spend_over_time", SpendOverTimeParams, build)
