"""Pure sync-window logic: first sync, incremental overlap, the no-bank-call skip, force."""

from datetime import UTC, datetime, timedelta

from finance_agent.categorize.rules import CategorizeResult
from finance_agent.ingest.pipeline import IngestResult
from finance_agent.reconcile.match import ReconcileResult
from finance_agent.sync_engine import plan_pull, summarize

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


def test_first_sync_pulls_a_bounded_history() -> None:
    plan = plan_pull(None, NOW, history_days=365)
    assert plan.should_pull
    assert plan.window is not None
    assert plan.window.reason == "first-sync"
    assert plan.window.end == NOW
    assert plan.window.start == NOW - timedelta(days=365)


def test_recent_pull_is_a_no_op_without_force() -> None:
    plan = plan_pull(NOW - timedelta(minutes=10), NOW)
    assert plan.should_pull is False
    assert plan.window is None
    assert plan.skip_reason is not None


def test_force_overrides_the_recent_guard() -> None:
    plan = plan_pull(NOW - timedelta(minutes=10), NOW, force=True)
    assert plan.should_pull
    assert plan.window is not None
    assert plan.window.reason == "incremental"


def test_incremental_window_overlaps_the_last_pull() -> None:
    last = NOW - timedelta(days=3)
    plan = plan_pull(last, NOW, overlap_days=5)
    assert plan.window is not None
    assert plan.window.start == last - timedelta(days=5)  # re-pull a tail for late postings
    assert plan.window.end == NOW


def test_summary_is_plain_language_and_counts_only() -> None:
    ingested = IngestResult(1, True, "ok", "v2", 2, 42, None)
    reconciled = ReconcileResult(
        matched=3, matched_low=0, updated=0, dissolved=0, unchanged=0, ambiguous=0
    )
    categorized = CategorizeResult(assigned=38, changed=0, unchanged=0, uncategorized=9)
    assert summarize(ingested, reconciled, categorized) == (
        "42 transactions, 3 transfers paired, 38 categorized, 9 need review"
    )
