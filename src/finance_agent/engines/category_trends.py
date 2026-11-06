"""Per-category monthly figures and a direction, over a fixed window of months."""

from collections.abc import Collection
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
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
    # Decided on the rounded change, the one that is displayed, so a badge never
    # contradicts the figure beside it (4.996% shows as +5.00% and is a trend).
    change = ((second - first) / abs(first)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)
    if abs(change) < FLAT_BAND:
        return "flat", change
    return ("rising" if change > 0 else "falling"), change


def category_trends(
    source: QueryResult[MonthlyCategorySpendRow],
    months: list[date],
    only: Collection[str] | None = None,
) -> QueryResult[TrendRow]:
    """Trends for each category in ``source`` across ``months`` (oldest first).

    The halves are the first and last ``len(months) // 2`` months; with an odd window the
    middle month is left out of both. Refunds are already netted in the source's spend.
    ``only`` keeps just those named categories (never the folded bucket) and is recorded in
    the result's params, so the figures are traceable to this exact selection. Money is
    rounded half-even, as the catalog's shares are.
    """
    if source.rows is None:
        raise ValueError("category_trends needs a monthly_spend_by_category result with rows")
    if not months:
        raise ValueError("category_trends needs at least one month")

    by_key: dict[tuple[bool, str | None], dict[date, Decimal]] = {}
    for row in source.rows:
        if only is None or (not row.is_other and row.category in only):
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
                average=(sum(monthly, Decimal(0)) / len(months)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_EVEN
                ),
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
            **({"categories": sorted(only)} if only is not None else {}),
        },
        result_id=f"category_trends:{source.result_id}",
        data_version=source.data_version,
        as_of=source.as_of,
        amounts_in=source.amounts_in,
        rows=rows,
    )
