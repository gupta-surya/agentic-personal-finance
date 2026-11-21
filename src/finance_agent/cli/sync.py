"""``finance sync``: one pull since the last successful sync, then reconcile and categorize."""

from datetime import datetime

from rich.console import Console

from finance_agent.cli.context import AppContext
from finance_agent.credentials import get_access_url
from finance_agent.ingest.simplefin.client import LiveSimpleFinClient, SimpleFinClient
from finance_agent.ingest.simplefin.errors import SimpleFinError
from finance_agent.sync_engine import run_sync


def run_sync_command(
    ctx: AppContext, *, force: bool = False, console: Console | None = None
) -> int:
    out = console or Console()
    if ctx.database_url() is None:
        out.print("Not set up yet. Run [bold]finance setup[/bold].")
        return 1
    now = ctx.now()
    try:
        with ctx.connect() as conn:
            access_url = get_access_url(conn, ctx.tenant_id, ctx.keystore)
            if access_url is None:
                out.print("No bank connected. Run [bold]finance setup[/bold].")
                return 1

            def make_client(start: datetime, end: datetime) -> SimpleFinClient:
                return LiveSimpleFinClient(access_url, now, start=start, end=end)

            outcome = run_sync(conn, ctx.tenant_id, now, ctx.tz, make_client, force=force)
    except SimpleFinError as err:
        out.print(f"[red]Sync failed:[/red] {err.message}")
        return 1
    except Exception:
        out.print("Database: [red]unavailable[/red]. Is Docker running?")
        return 1

    out.print(outcome.summary)
    return 0
