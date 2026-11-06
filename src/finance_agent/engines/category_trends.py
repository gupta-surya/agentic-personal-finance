"""Per-category monthly figures and a direction, over a fixed window of months."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from finance_agent.queries.result import Money, MonthlyCategorySpendRow, QueryResult, Share

Direction = Literal["rising", "falling", "flat", "insufficient_data"]

MIN_MONTHS = 4  # fewer cannot be split into two comparable halves
FLAT_BAND = Decimal("0.05")  # a swing of exactly 5% is a trend; under 5% is flat


class TrendRow(BaseModel):
    """One category over the window. ``monthly`` has one value per window month (a month with
    no spend is zero). ``average`` is per month, rounded to cents. ``change`` is the second
    half's total over the first's, minus one (``0.1234`` is +12.34%), or ``None`` when there is
    nothing to compare (too few months, or the first half spent nothing)."""

    model_config = ConfigDict(frozen=True)

    category: str | None  # None = uncategorized, or the folded bucket when is_other
    is_other: bool = False
    monthly: list[Money]
    average: Money
    minimum: Money
    maximum: Money
    direction: Direction
    change: Share | None


def _direction(first: Decimal, second: Decimal) -> tuple[Direction, Share | None]:
    if first == 0:
        return ("rising" if second > 0 else "flat"), None
    change = ((second - first) / abs(first)).quantize(Decimal("0.0001"))
    if abs(second - first) < FLAT_BAND * abs(first):
        return "flat", change
    return ("rising" if second > first else "falling"), change


def category_trends(
    source: QueryResult[MonthlyCategorySpendRow], months: list[date]
) -> QueryResult[TrendRow]:
    """Trends for each category in ``source`` across ``months`` (oldest first).

    The halves are the first and last ``len(months) // 2`` months; with an odd window the
    middle month is left out of both. Refunds are already netted in the source's spend.
    """
    if source.rows is None:
        raise ValueError("category_trends needs a monthly_spend_by_category result with rows")
    if not months:
        raise ValueError("category_trends needs at least one month")

    by_key: dict[tuple[bool, str | None], dict[date, Decimal]] = {}
    for row in source.rows:
        by_key.setdefault((row.is_other, row.category), {})[row.month] = row.spend

    half = len(months) // 2
    rows: list[TrendRow] = []
    # Alphabetical, with Uncategorized last and the folded bucket after it.
    for is_other, category in sorted(by_key, key=lambda k: (k[0], k[1] is None, k[1] or "")):
        monthly = [by_key[(is_other, category)].get(m, Decimal(0)) for m in months]
        if len(months) < MIN_MONTHS:
            direction, change = "insufficient_data", None
        else:
            direction, change = _direction(
                sum(monthly[:half], Decimal(0)), sum(monthly[-half:], Decimal(0))
            )
        rows.append(
            TrendRow(
                category=category,
                is_other=is_other,
                monthly=monthly,
                average=(sum(monthly, Decimal(0)) / len(months)).quantize(Decimal("0.01")),
                minimum=min(monthly),
                maximum=max(monthly),
                direction=direction,
                change=change,
            )
        )

    return QueryResult[TrendRow](
        query="category_trends",
        params={
            **source.params,
            "source_result_id": source.result_id,
            "months": [m.isoformat() for m in months],
        },
        result_id=f"category_trends:{source.result_id}",
        data_version=source.data_version,
        as_of=source.as_of,
        amounts_in=source.amounts_in,
        rows=rows,
    )
