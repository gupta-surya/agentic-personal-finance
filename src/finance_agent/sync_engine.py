"""One sync: decide the pull window, fetch once, then ingest -> reconcile -> categorize.

The window logic is pure and lives in ``plan_pull`` so it can be tested without a bank or a
database. Each downstream step owns its own transaction and is idempotent, so a repeated or
overlapping pull writes nothing new (bronze dedupes identical bytes; the silver loader and
the reconcile/categorize engines guard every write). The model is never called here
(categorization is rules-only; suggestions are a later task).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from finance_agent.categorize.rules import CategorizeResult, categorize
from finance_agent.db.loader import Connection
from finance_agent.ingest.pipeline import IngestResult, ingest
from finance_agent.ingest.simplefin.client import SimpleFinClient
from finance_agent.reconcile.match import ReconcileResult, reconcile

INITIAL_HISTORY_DAYS = 365  # first sync pulls a year so the charts have history
OVERLAP_DAYS = 5  # re-pull a short tail so late or amended postings are caught
MIN_RESYNC_INTERVAL = timedelta(hours=1)  # SimpleFIN allows ~24 pulls/day


@dataclass(frozen=True)
class PullWindow:
    start: datetime  # inclusive, timezone-aware
    end: datetime  # exclusive, timezone-aware
    reason: str  # "first-sync" | "incremental"


@dataclass(frozen=True)
class SyncPlan:
    should_pull: bool
    window: PullWindow | None
    skip_reason: str | None


@dataclass(frozen=True)
class SyncOutcome:
    pulled: bool
    skip_reason: str | None
    ingest: IngestResult | None
    reconcile: ReconcileResult | None
    categorize: CategorizeResult | None
    summary: str


def plan_pull(
    last_pull_at: datetime | None,
    now: datetime,
    *,
    force: bool = False,
    min_interval: timedelta = MIN_RESYNC_INTERVAL,
    history_days: int = INITIAL_HISTORY_DAYS,
    overlap_days: int = OVERLAP_DAYS,
) -> SyncPlan:
    """Decide whether to call the bank and for what window. ``now`` is injected, never read
    from the clock here."""
    if last_pull_at is None:
        start = now - timedelta(days=history_days)
        return SyncPlan(True, PullWindow(start, now, "first-sync"), None)
    if not force and now - last_pull_at < min_interval:
        return SyncPlan(
            False, None, "already synced in the last hour; run with --force to pull again"
        )
    start = last_pull_at - timedelta(days=overlap_days)
    return SyncPlan(True, PullWindow(start, now, "incremental"), None)


def summarize(
    ingested: IngestResult, reconciled: ReconcileResult, categorized: CategorizeResult
) -> str:
    """One plain-language line. No merchant text, amounts or account names."""
    parts = [f"{ingested.transactions} transactions"]
    if reconciled.matched:
        parts.append(f"{reconciled.matched} transfers paired")
    if categorized.assigned:
        parts.append(f"{categorized.assigned} categorized")
    if categorized.uncategorized:
        parts.append(f"{categorized.uncategorized} need review")
    return ", ".join(parts)


def last_successful_pull_at(conn: Connection, tenant_id: str) -> datetime | None:
    row = conn.execute(
        "SELECT max(fetched_at) FROM raw_pulls "
        "WHERE tenant_id = %s AND source = 'simplefin' AND parse_status = 'ok'",
        (tenant_id,),
    ).fetchone()
    return row[0] if row and row[0] is not None else None


def run_sync(
    conn: Connection,
    tenant_id: str,
    now: datetime,
    tz: ZoneInfo,
    make_client: Callable[[datetime, datetime], SimpleFinClient],
    *,
    force: bool = False,
    min_interval: timedelta = MIN_RESYNC_INTERVAL,
) -> SyncOutcome:
    """Fetch once for the planned window, then ingest, reconcile and categorize.

    A fetch failure (bank down, revoked token) raises before any write, so stored data is
    untouched. ``make_client`` builds the bank client for ``(start, end)``; tests inject a
    fixture client so no network is used.
    """
    plan = plan_pull(
        last_successful_pull_at(conn, tenant_id), now, force=force, min_interval=min_interval
    )
    if not plan.should_pull or plan.window is None:
        reason = plan.skip_reason or "nothing to do"
        return SyncOutcome(False, reason, None, None, None, reason)

    pull = make_client(plan.window.start, plan.window.end).fetch()
    ingested = ingest(conn, tenant_id, pull, tz)
    if ingested.status != "ok":
        note = ingested.message or ingested.status
        return SyncOutcome(
            True, None, ingested, None, None, f"received data but could not process it: {note}"
        )

    reconciled = reconcile(conn, tenant_id)
    categorized = categorize(conn, tenant_id)
    return SyncOutcome(
        True, None, ingested, reconciled, categorized, summarize(ingested, reconciled, categorized)
    )
