"""A request-scoped, read-only ``PostgresSeriesCatalog`` for the chart API."""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.conninfo import conninfo_to_dict

from finance_agent.charts.api import CatalogUnavailable
from finance_agent.queries.pg_catalog import PostgresSeriesCatalog


def check_database_url(url: str) -> None:
    """Refuse a ``*_test`` database: the test suite drops its schema, so a mis-set variable
    must never point the app at one. The database must be named in the URL itself (not left
    to ``PGDATABASE`` or a service file). Messages never echo the URL."""
    try:
        name = str(conninfo_to_dict(url).get("dbname", ""))
    except psycopg.ProgrammingError:  # psycopg's message can quote the URL, password included
        raise ValueError("CHARTS_DATABASE_URL is not a valid connection URL") from None
    if not name or name.lower().endswith("_test"):
        raise ValueError(
            f"refusing to serve charts from database {name!r}: use a non-test database"
        )


@contextmanager
def postgres_session(url: str, tenant_id: str) -> Iterator[PostgresSeriesCatalog]:
    """One connection per request, opened read-only and closed on exit, so the chart API
    cannot write. A connection that cannot be made or has dropped becomes
    ``CatalogUnavailable`` (no details); a failing query is a bug and stays a loud 500."""
    try:
        with psycopg.connect(url) as conn:
            conn.read_only = True
            yield PostgresSeriesCatalog(conn, tenant_id)
    except (psycopg.OperationalError, psycopg.InterfaceError):
        raise CatalogUnavailable from None
