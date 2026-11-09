"""``finance status``: is the database reachable, is the bank connected, when did we last
sync, and is the model available. No secrets, hosts, amounts or account names are printed.
"""

from rich.console import Console

from finance_agent.cli.context import AppContext
from finance_agent.credentials import has_access_url
from finance_agent.model_gateway.config import ModelConfig
from finance_agent.model_gateway.health import check, model_status_signal
from finance_agent.sync_engine import last_successful_pull_at


def run_status(ctx: AppContext, console: Console | None = None) -> int:
    out = console or Console()
    if ctx.database_url() is None:
        out.print("Not set up yet. Run [bold]finance setup[/bold].")
        return 1
    try:
        with ctx.connect() as conn:
            bank = "connected" if has_access_url(conn, ctx.tenant_id) else "not connected"
            last = last_successful_pull_at(conn, ctx.tenant_id)
    except Exception:
        out.print("Database: [red]unavailable[/red]. Is Docker running? Try `finance setup`.")
        return 1

    out.print("Database: [green]ok[/green]")
    out.print(f"Bank: {bank}")
    out.print(f"Last sync: {last.isoformat() if last else 'never'}")

    signal = model_status_signal(check(ModelConfig.from_env()))
    out.print(f"Model: {signal or 'ok'}")
    return 0
