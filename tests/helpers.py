"""Shared test helpers for building pulls and ingesting fixtures."""

import os
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from zoneinfo import ZoneInfo

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from finance_agent.clients.simplefin import FixtureSimpleFinClient
from finance_agent.db.loader import Connection
from finance_agent.ingest.contract import RawPull
from finance_agent.ingest.pipeline import IngestResult, ingest

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
FETCHED_AT = datetime(2026, 4, 2, 12, 0, tzinfo=UTC)
UTC_TZ = ZoneInfo("UTC")


def pull_from_text(body: str | bytes, source: str = "simplefin") -> RawPull:
    data = body.encode("utf-8") if isinstance(body, str) else body
    return RawPull(source=source, body=data, fetched_at=FETCHED_AT)


def pull_from_file(name: str) -> RawPull:
    return FixtureSimpleFinClient(FIXTURES / name, FETCHED_AT).fetch()


def ingest_file(conn: Connection, tenant_id: str, name: str, tz: ZoneInfo = UTC_TZ) -> IngestResult:
    return ingest(conn, tenant_id, pull_from_file(name), tz)


def database_url() -> str:
    return os.environ.get(
        "TEST_DATABASE_URL", "postgresql://finance:finance@127.0.0.1:5432/finance_test"
    )


def alembic(action: str, revision: str) -> None:
    """Run ``alembic upgrade|downgrade <revision>`` against the test database."""
    url = os.environ.get(
        "TEST_DATABASE_URL", "postgresql://finance:finance@127.0.0.1:5432/finance_test"
    ).replace("postgresql://", "postgresql+psycopg://", 1)
    config = Config()
    config.set_main_option("script_location", str(files("finance_agent.db") / "migrations"))
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            getattr(command, action)(config, revision)
    finally:
        engine.dispose()
