"""``finance review``: list uncategorized transactions and set a category for each.

Descriptions come from the bank and are untrusted: each is neutralized with
``sanitize_for_display`` before printing. Suggested categories (TASK-04c) plug in here later.
"""

from rich.console import Console

from finance_agent.categorize.actions import correct_category
from finance_agent.cli.context import AppContext
from finance_agent.cli.prompts import Prompter
from finance_agent.db.loader import Connection
from finance_agent.ingest.sanitize import sanitize_for_display

SKIP = "skip"


def _uncategorized(conn: Connection, tenant_id: str, limit: int = 50) -> list[tuple[int, str]]:
    rows = conn.execute(
        """
        SELECT id, description FROM transactions
        WHERE tenant_id = %s AND category IS NULL AND is_internal_transfer = false
          AND posted_date IS NOT NULL
        ORDER BY posted_date DESC, id
        LIMIT %s
        """,
        (tenant_id, limit),
    ).fetchall()
    return [(int(r[0]), str(r[1])) for r in rows]


def _categories(conn: Connection, tenant_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM categories WHERE tenant_id = %s ORDER BY name", (tenant_id,)
    ).fetchall()
    return [str(r[0]) for r in rows]


def run_review(
    ctx: AppContext,
    prompter: Prompter,
    *,
    non_interactive: bool = False,
    console: Console | None = None,
) -> int:
    out = console or Console()
    if ctx.database_url() is None:
        out.print("Not set up yet. Run [bold]finance setup[/bold].")
        return 1
    with ctx.connect() as conn:
        rows = _uncategorized(conn, ctx.tenant_id)
        if not rows:
            out.print("Nothing to review.")
            return 0
        if non_interactive:
            for _id, description in rows:
                out.print(sanitize_for_display(description))
            return 0
        options = [*_categories(conn, ctx.tenant_id), SKIP]
        for txn_id, description in rows:
            choice = prompter.select(sanitize_for_display(description), options)
            if choice and choice != SKIP:
                correct_category(conn, ctx.tenant_id, txn_id, choice)
                conn.commit()
    out.print("Done.")
    return 0
