"""``finance serve``: run the local charts API against your data (or synthetic).

Reads the database URL from the local config, so mode B is one command. Nothing here calls a
model; it is the chart/aggregate API the web app talks to.
"""

import os
from collections.abc import Callable
from datetime import date, datetime
from functools import partial
from typing import Any

from rich.console import Console

from finance_agent.cli.context import AppContext

Server = Callable[[Any, str, int], None]
SYNTHETIC_TODAY = date(2026, 10, 25)  # the synthetic sample's range is Sep 2025 - Oct 2026


def _default_server(app: Any, host: str, port: int) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port)


def _today(synthetic: bool) -> date:
    pinned = os.environ.get("CHARTS_TODAY")
    if pinned:
        return date.fromisoformat(pinned)
    return SYNTHETIC_TODAY if synthetic else datetime.now().astimezone().date()


def build_server_app(ctx: AppContext, *, synthetic: bool) -> Any:
    """Build the FastAPI charts app. Raises RuntimeError if no database is configured."""
    from finance_agent.charts.api import create_app
    from finance_agent.charts.templates import default_registry

    registry = default_registry()
    today = partial(_today, synthetic)
    if synthetic:
        from finance_agent.charts.fake_catalog import fake_session

        return create_app(registry, fake_session, today)
    url = ctx.database_url()
    if url is None:
        raise RuntimeError("not set up yet; run `finance setup` first")
    from finance_agent.charts.postgres import check_database_url, postgres_session

    check_database_url(url)
    return create_app(
        registry, partial(postgres_session, url, ctx.tenant_id), today, source="postgres"
    )


def run_serve(
    ctx: AppContext,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    synthetic: bool = False,
    server: Server = _default_server,
    console: Console | None = None,
) -> int:
    out = console or Console()
    try:
        app = build_server_app(ctx, synthetic=synthetic)
    except RuntimeError as err:
        out.print(f"[red]{err}[/red]")
        return 1
    label = "synthetic data" if synthetic else "your data"
    out.print(f"Charts API ({label}) on http://{host}:{port}")
    out.print("In another terminal: [bold]cd web && npm run dev[/bold]  ->  http://127.0.0.1:5173")
    server(app, host, port)
    return 0
