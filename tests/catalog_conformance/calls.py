"""The call matrix both implementations are run through."""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from finance_agent.queries.result import QueryResult
from finance_agent.queries.series import SeriesCatalog

FULL = (date(2025, 9, 1), date(2026, 11, 1))
MARCH = (date(2026, 3, 1), date(2026, 4, 1))
FEBRUARY = (date(2026, 2, 1), date(2026, 3, 1))
OCTOBER = (date(2026, 10, 1), date(2026, 11, 1))  # holds the pending charge
PARTIAL = (date(2026, 3, 10), date(2026, 5, 20))  # starts and ends mid-month
BEFORE = (date(2020, 1, 1), date(2020, 2, 1))
AFTER = (date(2030, 1, 1), date(2030, 2, 1))
ZERO_WIDTH = (date(2026, 3, 1), date(2026, 3, 1))
REVERSED = (date(2026, 4, 1), date(2026, 3, 1))
EDGE_LOW = (date(2026, 3, 22), date(2026, 3, 23))  # a row on start is included
EDGE_HIGH = (date(2026, 3, 1), date(2026, 3, 22))  # a row on end is excluded
TIE_DAY = (date(2026, 6, 25), date(2026, 6, 26))  # three groups tie at 40.00

RANGES = {
    "full": FULL,
    "march": MARCH,
    "february": FEBRUARY,
    "october": OCTOBER,
    "partial": PARTIAL,
    "before": BEFORE,
    "after": AFTER,
    "zero_width": ZERO_WIDTH,
    "reversed": REVERSED,
    "edge_low": EDGE_LOW,
    "edge_high": EDGE_HIGH,
    "tie_day": TIE_DAY,
}


@dataclass(frozen=True)
class Call:
    id: str
    method: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any] = field(default_factory=dict)


def _matrix() -> list[Call]:
    calls: list[Call] = []
    for name, (start, end) in RANGES.items():
        for currency in ("USD", "EUR", "GBP") if name in ("full", "march", "before") else ("USD",):
            calls.append(Call(f"cash_flow {name} {currency}", "cash_flow", (start, end, currency)))
            for method in ("monthly_spend_by_category", "spend_breakdown"):
                for top_n in (
                    (None, 1, 2, 3, 50) if name in ("full", "march", "tie_day") else (None,)
                ):
                    calls.append(
                        Call(
                            f"{method} {name} {currency} top_n={top_n}",
                            method,
                            (start, end, currency),
                            {"top_n": top_n},
                        )
                    )
        for measure in ("spend", "income", "net"):
            calls.append(Call(f"kpi {measure} {name}", "kpi", (measure, start, end, "USD")))
    for currency in ("EUR", "GBP"):
        for measure in ("spend", "income", "net"):
            calls.append(Call(f"kpi {measure} {currency}", "kpi", (measure, *MARCH, currency)))
    for category in ("groceries", "dining", "rent", "transport", "income", "", "nonexistent"):
        for name in ("full", "march", "partial", "before"):
            calls.append(
                Call(
                    f"kpi spend {name} category={category!r}",
                    "kpi",
                    ("spend", *RANGES[name], "USD"),
                    {"category": category},
                )
            )
    # Errors both must raise.
    for method in ("monthly_spend_by_category", "spend_breakdown"):
        for bad in (0, -3):
            calls.append(Call(f"{method} top_n={bad}", method, (*MARCH, "USD"), {"top_n": bad}))
    for measure in ("income", "net"):
        calls.append(
            Call(
                f"kpi {measure} with a category",
                "kpi",
                (measure, *MARCH, "USD"),
                {"category": "groceries"},
            )
        )
    return calls


CALLS = _matrix()

RAISED = "ValueError"


def invoke(catalog: SeriesCatalog, call: Call) -> QueryResult[Any] | str:
    """Run one call; a ``ValueError`` is returned as the ``RAISED`` marker."""
    try:
        result: QueryResult[Any] = getattr(catalog, call.method)(*call.args, **call.kwargs)
    except ValueError:
        return RAISED
    return result


def comparable(result: QueryResult[Any] | str) -> dict[str, Any] | str:
    """Everything that must be identical; excludes result_id, data_version and as_of."""
    if isinstance(result, str):
        return result
    return {
        "query": result.query,
        "params": result.params,
        "amounts_in": result.amounts_in,
        "value": result.value,
        "rows": None if result.rows is None else [row.model_dump() for row in result.rows],
        "totals": result.totals,
    }
