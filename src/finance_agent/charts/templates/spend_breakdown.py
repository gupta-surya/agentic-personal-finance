"""``spend_breakdown``: "Where did my money go in September?"

Amount and share per group, copied from the ``spend_breakdown`` query, which also does
the ranking, the top-N fold and the shares. The builder labels and orders nothing it was
not given: rows keep the catalog's order (largest first, the folded bucket last).
"""

from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from finance_agent.charts.period import Period, resolve_period
from finance_agent.charts.registry import Template
from finance_agent.charts.spec import Assumption, ChartSpec, Point, Series, Table
from finance_agent.charts.templates.common import (
    category_label,
    format_money,
    format_share,
    source_of,
    span_label,
)
from finance_agent.queries.series import BreakdownGroupBy, SeriesCatalog


class SpendBreakdownParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: Literal["spend_breakdown"]
    period: Period
    group_by: BreakdownGroupBy = "category"
    top_n: int = Field(default=8, ge=1, le=12)
    currency: str = "USD"


def build(params: SpendBreakdownParams, catalog: SeriesCatalog, today: date) -> ChartSpec:
    period = resolve_period(params.period, today)
    result = catalog.spend_breakdown(
        period.start, period.end, params.currency, group_by=params.group_by, top_n=params.top_n
    )
    if result.rows is None:
        raise ValueError("spend_breakdown must return rows")
    rows = result.rows
    cur = params.currency
    labels = [category_label(r.group, is_other=r.is_other) for r in rows]
    span = span_label(period.start, period.end - timedelta(days=1))

    if rows and rows[0].amount > 0:
        title = (
            f"{labels[0]} took the biggest share of spending, {format_share(rows[0].share)}, {span}"
        )
    else:
        title = f"Where your money went, {span}"

    assumptions = [
        Assumption(key="currency", label="Currency", value=cur, source="default"),
        Assumption(key="group_by", label="Grouped by", value="Category", source="default"),
        Assumption(
            key="top_n",
            label="Groups shown",
            value=f"Top {params.top_n}; the rest are grouped as Everything else",
            source="default",
        ),
    ]
    if "spend" in result.totals:
        assumptions.append(
            Assumption(
                key="total",
                label="Total spend",
                value=format_money(result.totals["spend"], cur),
                source="data",
            )
        )
    if any(r.amount < 0 for r in rows):
        assumptions.append(
            Assumption(
                key="refunds",
                label="Note",
                value=(
                    "Refunds can make a group's net spend negative; shares are of net total spend"
                ),
                source="data",
            )
        )

    series = (
        [
            Series(
                id="amount",
                kind="bar",
                label="Spend",
                result_id=result.result_id,
                points=[Point(x=label, y=r.amount) for label, r in zip(labels, rows, strict=True)],
            ),
            Series(
                id="share",
                kind="point",
                label="Share of total",
                result_id=result.result_id,
                points=[Point(x=label, y=r.share) for label, r in zip(labels, rows, strict=True)],
            ),
        ]
        if rows
        else []
    )
    return ChartSpec(
        template_id="spend_breakdown",
        title=title,
        params=params.model_dump(mode="json"),
        period=period,
        series=series,
        assumptions=assumptions,
        sources=[source_of(result)],
        table=Table(
            columns=["Category", "Spend", "Share"],
            rows=[
                [label, format_money(r.amount, cur), format_share(r.share)]
                for label, r in zip(labels, rows, strict=True)
            ],
        ),
    )


TEMPLATE = Template("spend_breakdown", SpendBreakdownParams, build)
