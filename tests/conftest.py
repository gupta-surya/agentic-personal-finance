import os
from collections.abc import Iterator

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from finance_agent.db.default_categories import seed_default_categories
from finance_agent.db.loader import Connection, apply_schema

DEFAULT_TEST_DATABASE_URL = "postgresql://finance:finance@127.0.0.1:5432/finance_test"


@pytest.fixture
def conn() -> Iterator[Connection]:
    """A connection to a freshly reset test database.

    Fails (never skips) when Postgres is unreachable: start it with
    `docker compose up -d`.
    """
    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    dbname = str(conninfo_to_dict(url).get("dbname", ""))
    if not dbname.endswith("_test"):
        raise RuntimeError(f"refusing to reset non-test database {dbname!r}")

    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
        apply_schema(connection)
        # Categories are a foreign key target; the demo tenant needs its taxonomy.
        seed_default_categories(connection, "demo-tenant")
        yield connection
