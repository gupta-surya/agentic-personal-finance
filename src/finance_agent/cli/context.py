"""Shared wiring for the commands: paths, stores, the clock, and database connections.

One place reads the environment and the wall clock; the commands receive everything by the
context so their logic stays testable.
"""

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import psycopg

from finance_agent.crypto import FileKeyStore
from finance_agent.db.loader import Connection
from finance_agent.provision import TENANT_ID, guard_not_test_db
from finance_agent.secrets import (
    DATABASE_URL,
    FileSecretStore,
    default_config_path,
    default_keys_path,
)


@dataclass(frozen=True)
class AppContext:
    config: FileSecretStore
    keystore: FileKeyStore
    tenant_id: str
    tz: ZoneInfo

    def now(self) -> datetime:
        return datetime.now(UTC)

    def database_url(self) -> str | None:
        return self.config.get(DATABASE_URL)

    def connect(self) -> Connection:
        """Open the app database, read-write. Refuses a ``*_test`` database (invariant: the
        suite resets those)."""
        url = self.database_url()
        if url is None:
            raise RuntimeError("not set up yet; run `finance setup` first")
        guard_not_test_db(url)
        return psycopg.connect(url)


def default_context() -> AppContext:
    tz_name = os.environ.get("FINANCE_TZ", "UTC")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    return AppContext(
        config=FileSecretStore(default_config_path()),
        keystore=FileKeyStore(default_keys_path()),
        tenant_id=TENANT_ID,
        tz=tz,
    )
