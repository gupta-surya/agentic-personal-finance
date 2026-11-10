"""The ``finance`` entry point. Thin Typer wiring over the command functions."""

from pathlib import Path

import typer

from finance_agent.cli.context import default_context
from finance_agent.cli.prompts import QuestionaryPrompter
from finance_agent.cli.review import run_review
from finance_agent.cli.setup import run_setup
from finance_agent.cli.status import run_status
from finance_agent.cli.sync import run_sync_command

app = typer.Typer(add_completion=False, help="Private, local personal finance on your own data.")

_TOKEN_FILE = typer.Option(None, "--token-file", help="Read the setup token from a file.")
_YES = typer.Option(False, "--yes", help="Accept defaults; do not prompt.")
_FORCE = typer.Option(False, "--force", help="Pull again even if a recent sync exists.")
_LIST_ONLY = typer.Option(False, "--yes", help="List only; do not prompt.")


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


def main() -> None:
    app()
