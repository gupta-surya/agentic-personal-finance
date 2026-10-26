"""Helpers shared by the template builders. Formatting only: nothing here computes a
money figure. Builders copy values out of ``QueryResult``s and label them."""

from datetime import date
from decimal import Decimal
from typing import Any

from finance_agent.charts.spec import Source
from finance_agent.queries.result import QueryResult

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£"}

UNCATEGORIZED = "Uncategorized"
OTHER = "Other"


def format_money(amount: Decimal, currency: str = "USD") -> str:
    """``Decimal("-210.75")`` -> ``"−$210.75"``. Digits are kept as given (padded to
    two places); only grouping and the sign are added, so nothing is rounded."""
    whole, _, fraction = format(abs(amount), "f").partition(".")
    symbol = _SYMBOLS.get(currency, f"{currency} ")
    sign = "−" if amount < 0 else ""
    return f"{sign}{symbol}{int(whole):,}.{fraction.ljust(2, '0')}"


def month_label(day: date) -> str:
    """``date(2026, 3, 1)`` -> ``"Mar 2026"``."""
    return f"{_MONTHS[day.month - 1]} {day.year}"


def span_label(first: date, last: date) -> str:
    """``"Mar 2026"`` for one month, ``"Apr 2026 – Sep 2026"`` for a range."""
    if (first.year, first.month) == (last.year, last.month):
        return month_label(first)
    return f"{month_label(first)} – {month_label(last)}"


def source_of(result: QueryResult[Any]) -> Source:
    return Source(
        result_id=result.result_id,
        query=result.query,
        data_version=result.data_version,
        as_of=result.as_of,
    )
