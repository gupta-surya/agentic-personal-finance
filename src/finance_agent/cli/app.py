"""The ``finance`` entry point. Thin Typer wiring over the command functions."""

from pathlib import Path

import typer

from finance_agent.cli.context import default_context
from finance_agent.cli.prompts import QuestionaryPrompter
from finance_agent.cli.review import run_review
from finance_agent.cli.serve import run_serve
from finance_agent.cli.setup import run_setup
from finance_agent.cli.status import run_status
from finance_agent.cli.sync import run_sync_command

app = typer.Typer(add_completion=False, help="Private, local personal finance on your own data.")

_TOKEN_FILE = typer.Option(None, "--token-file", help="Read the setup token from a file.")
_YES = typer.Option(False, "--yes", help="Accept defaults; do not prompt.")
_FORCE = typer.Option(False, "--force", help="Pull again even if a recent sync exists.")
_LIST_ONLY = typer.Option(False, "--yes", help="List only; do not prompt.")
_SYNTHETIC = typer.Option(False, "--synthetic", help="Serve synthetic sample data.")
_AGENT = typer.Option(False, "--agent", help="Also serve /ask (needs Ollama).")
_HOST = typer.Option("127.0.0.1", "--host", help="Bind host.")
_PORT = typer.Option(8000, "--port", help="Bind port.")
_LAN = typer.Option(False, "--i-understand-lan", help="Allow binding beyond 127.0.0.1.")


@app.command()
def setup(token_file: Path | None = _TOKEN_FILE, yes: bool = _YES) -> None:
    """Guided first-time setup: machine check, database, bank, accounts, first sync."""
    token = token_file.read_text(encoding="utf-8").strip() if token_file else None
    code = run_setup(default_context(), QuestionaryPrompter(), token=token, assume_yes=yes)
    raise typer.Exit(code)


@app.command()
def sync(force: bool = _FORCE) -> None:
    """Pull new transactions since the last sync, then reconcile and categorize."""
    raise typer.Exit(run_sync_command(default_context(), force=force))


@app.command()
def status() -> None:
    """Show database, bank, last-sync and model status."""
    raise typer.Exit(run_status(default_context()))


@app.command()
def review(yes: bool = _LIST_ONLY) -> None:
    """Review and categorize transactions rules did not cover."""
    raise typer.Exit(run_review(default_context(), QuestionaryPrompter(), non_interactive=yes))


@app.command()
def serve(
    synthetic: bool = _SYNTHETIC,
    agent: bool = _AGENT,
    host: str = _HOST,
    port: int = _PORT,
    i_understand_lan: bool = _LAN,
) -> None:
    """Run the local charts API (your data, or --synthetic). Pair with `cd web && npm run dev`."""
    raise typer.Exit(
        run_serve(
            default_context(),
            host=host,
            port=port,
            synthetic=synthetic,
            agent=agent,
            i_understand_lan=i_understand_lan,
        )
    )


def main() -> None:
    app()
