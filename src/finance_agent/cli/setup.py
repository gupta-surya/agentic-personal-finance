"""``finance setup``: from nothing to a first sync of real data, in six guided steps.

The user never edits a file, sets an environment variable, sees a database or reads SQL.
Re-running is safe: finished steps are detected and skipped. No model is called here.
"""

import time
from datetime import datetime

import psycopg
from rich.console import Console

from finance_agent.cli.context import AppContext
from finance_agent.cli.database import (
    ADMIN_URL,
    app_database_url,
    compose_up_db,
    ensure_role_and_database,
    random_password,
)
from finance_agent.cli.environment import Runner, check_docker, check_ollama
from finance_agent.cli.environment import _run as default_runner
from finance_agent.cli.prompts import Prompter
from finance_agent.credentials import get_access_url, has_access_url, store_access_url
from finance_agent.ingest.pipeline import ingest
from finance_agent.ingest.sanitize import sanitize_for_display
from finance_agent.ingest.simplefin.client import LiveSimpleFinClient, claim_access_url
from finance_agent.ingest.simplefin.errors import SimpleFinError
from finance_agent.reconcile.actions import set_account_role
from finance_agent.secrets import DATABASE_URL
from finance_agent.sync_engine import run_sync


def _wait_for_db(url: str, attempts: int = 30) -> bool:
    for _ in range(attempts):
        try:
            with psycopg.connect(url, connect_timeout=2):
                return True
        except psycopg.OperationalError:
            time.sleep(1)
    return False


def run_setup(
    ctx: AppContext,
    prompter: Prompter,
    *,
    token: str | None = None,
    assume_yes: bool = False,
    runner: Runner = default_runner,
    console: Console | None = None,
) -> int:
    out = console or Console()

    # 1/6 machine
    docker = check_docker(runner=runner)
    ollama = check_ollama(runner=runner)
    out.print(f"1/6  Checking your machine ... Docker {docker.detail}, Ollama {ollama.detail}")
    if not docker.running:
        out.print(f"      Docker is required. Install or start it: {docker.install_url}")
        return 1

    # 2/6 database
    out.print("2/6  Your private database ...")
    code, _ = compose_up_db(runner)
    if code != 0 or not _wait_for_db(ADMIN_URL):
        out.print("      Could not start the local database with Docker.")
        return 1
    url = ctx.database_url()
    if url is None:
        password = random_password()
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            ensure_role_and_database(admin, password=password)
        url = app_database_url(password)
        ctx.config.set(DATABASE_URL, url)
    from finance_agent.provision import provision_schema_and_seed

    with psycopg.connect(url) as conn:
        provision_schema_and_seed(conn, ctx.tenant_id)
        conn.commit()
    out.print("      created (your data stays on this computer)")

    # 3/6 connect the bank (resume-safe)
    with psycopg.connect(url) as conn:
        if has_access_url(conn, ctx.tenant_id):
            out.print("3/6  Connect your bank ... already connected")
        else:
            setup_token = token or prompter.secret("3/6  Paste your SimpleFIN setup token:")
            try:
                access_url = claim_access_url(setup_token)
            except SimpleFinError as err:
                out.print(f"      {err.message}")
                return 1
            store_access_url(conn, ctx.tenant_id, access_url, ctx.keystore, ctx.now())
            conn.commit()
            out.print("3/6  Connect your bank ... connected")

    # 4/6 accounts and roles
    with psycopg.connect(url) as conn:
        bank_url = get_access_url(conn, ctx.tenant_id, ctx.keystore)
        assert bank_url is not None
        try:
            pull = LiveSimpleFinClient(bank_url, ctx.now(), balances_only=True).fetch()
        except SimpleFinError as err:
            out.print(f"      {err.message}")
            return 1
        ingest(conn, ctx.tenant_id, pull, ctx.tz)
        conn.commit()
        accounts = conn.execute(
            "SELECT id, name FROM accounts WHERE tenant_id = %s ORDER BY id", (ctx.tenant_id,)
        ).fetchall()
        out.print(f"4/6  Your accounts ... found {len(accounts)}")
        labels = {
            f"{sanitize_for_display(str(name))}  (#{aid})": int(aid) for aid, name in accounts
        }
        if accounts and not assume_yes:
            chosen = prompter.multiselect(
                "      Which are credit cards or loans? (space to select)", list(labels)
            )
            for label in chosen:
                set_account_role(conn, ctx.tenant_id, labels[label], "credit")
            conn.commit()

    # 5/6 first sync
    now = ctx.now()
    with psycopg.connect(url) as conn:
        bank_url = get_access_url(conn, ctx.tenant_id, ctx.keystore)
        assert bank_url is not None

        def make_client(start: datetime, end: datetime) -> LiveSimpleFinClient:
            return LiveSimpleFinClient(bank_url, now, start=start, end=end)

        try:
            outcome = run_sync(conn, ctx.tenant_id, now, ctx.tz, make_client, force=True)
        except SimpleFinError as err:
            out.print(f"      {err.message}")
            return 1
        conn.commit()
    out.print(f"5/6  First sync ... {outcome.summary}")

    # 6/6 done
    out.print("6/6  Done. Run `finance sync` any time; `finance review` to confirm the rest.")
    if not ollama.running:
        out.print("      (Ollama is optional; without it, new merchants stay uncategorized.)")
    return 0
