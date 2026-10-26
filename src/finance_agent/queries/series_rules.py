"""Pure rules every ``SeriesCatalog`` implementation shares, so they cannot drift.

The fake catalog and the Postgres catalog both rank, round and describe their
arguments through these functions. Nothing here touches a database.
"""

from datetime import date
from decimal import Decimal
from typing import Any


def top_groups(totals: dict[str | None, Decimal], top_n: int) -> set[str | None]:
    """The N groups with the largest net spend; ties by name, uncategorized last."""
    if top_n < 1:
        raise ValueError("top_n must be at least 1")
    ranked = sorted(totals, key=lambda g: (-totals[g], g is None, g or ""))
    return set(ranked[:top_n])


def share(amount: Decimal, total: Decimal) -> Decimal:
    """``amount / total`` rounded to four places (``0.1234`` is 12.34%); 0 for a zero total."""
    return (amount / total).quantize(Decimal("0.0001")) if total else Decimal("0")


def catalog_params(
    start: date, end: date, currency: str, **extra: str | int | None
) -> dict[str, Any]:
    """The resolved arguments echoed in ``QueryResult.params``; ``None`` extras are omitted."""
    params: dict[str, Any] = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "currency": currency,
    }
    params.update({k: v for k, v in extra.items() if v is not None})
    return params
