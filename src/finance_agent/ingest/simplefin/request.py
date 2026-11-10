"""Request parameters for SimpleFIN's ``GET /accounts``. Pure: no HTTP here.

Pending transactions are excluded by the server unless ``pending=1`` is sent, so a
pull that wants them must ask. ``balances_only`` asks the server to omit
transactions (used to discover accounts without pulling history). The chosen
parameters are recorded in bronze; the access URL and its credentials never are.
"""

from datetime import datetime


def _epoch(moment: datetime, name: str) -> str:
    if moment.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return str(int(moment.timestamp()))


def simplefin_request_params(
    version: int,
    start: datetime | None = None,
    end: datetime | None = None,
    include_pending: bool = True,
    balances_only: bool = False,
) -> dict[str, str]:
    """Query parameters for ``/accounts``. ``start`` is inclusive, ``end`` exclusive."""
    params = {"version": str(version)}
    if balances_only:
        params["balances-only"] = "1"
    if include_pending:
        params["pending"] = "1"
    if start is not None:
        params["start-date"] = _epoch(start, "start")
    if end is not None:
        params["end-date"] = _epoch(end, "end")
    return params
