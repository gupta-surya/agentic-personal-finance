"""run_sync end to end (needs Postgres: `docker compose up -d`).

Uses the demo SimpleFIN fixture through a fixture client, so no network is touched. Proves
the first sync ingests/reconciles/categorizes, a second call within the interval makes no
bank request, and --force re-pulls but bronze dedupes the identical bytes.
"""

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from finance_agent.db.loader import Connection
from finance_agent.ingest.simplefin.client import FixtureSimpleFinClient, SimpleFinClient
from finance_agent.sync_engine import run_sync

FIXTURE = Path("fixtures/simplefin_demo.json")
TZ = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


def _make_client(*_: datetime, fetched_at: datetime = NOW) -> SimpleFinClient:
    return FixtureSimpleFinClient(FIXTURE, fetched_at=fetched_at, request_params={"version": "2"})


def test_first_sync_runs_the_whole_pipeline(conn: Connection) -> None:
    out = run_sync(conn, "demo-tenant", NOW, TZ, lambda s, e: _make_client())
    assert out.pulled is True
    assert out.ingest is not None and out.ingest.status == "ok"
    assert out.reconcile is not None
    assert out.categorize is not None
    assert "transactions" in out.summary


def test_second_sync_within_interval_makes_no_bank_request(conn: Connection) -> None:
    calls: list[int] = []

    def counting(_s: datetime, _e: datetime) -> SimpleFinClient:
        calls.append(1)
        return _make_client()

    run_sync(conn, "demo-tenant", NOW, TZ, counting)
    out = run_sync(conn, "demo-tenant", NOW, TZ, counting)  # same instant
    assert out.pulled is False
    assert len(calls) == 1  # the bank was called once, not twice


def test_force_repulls_but_bronze_dedupes_identical_bytes(conn: Connection) -> None:
    run_sync(conn, "demo-tenant", NOW, TZ, lambda s, e: _make_client())
    out = run_sync(conn, "demo-tenant", NOW, TZ, lambda s, e: _make_client(), force=True)
    assert out.pulled is True
    assert out.ingest is not None and out.ingest.created is False  # same bytes, deduped
