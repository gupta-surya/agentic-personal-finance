"""Provision the one local database the app uses: apply the schema, seed its taxonomy.

The developer test database (``*_test``) is reset by the suite, so the app refuses it
everywhere (``guard_not_test_db``). Creating the database and its role lives in the setup
command, which also manages Docker; this module is the in-database part, which is what the
tests exercise.
"""

from psycopg.conninfo import conninfo_to_dict

from finance_agent.categorize.starter_rules import seed_starter_rules
from finance_agent.db.default_categories import seed_default_categories
from finance_agent.db.loader import Connection, apply_schema

TENANT_ID = "local"


class DatabaseIsTestError(RuntimeError):
    """A ``*_test`` database was given for real use; the suite resets those."""


def _dbname(url_or_name: str) -> str:
    if "://" in url_or_name or "=" in url_or_name:
        return str(conninfo_to_dict(url_or_name).get("dbname", ""))
    return url_or_name


def guard_not_test_db(url_or_name: str) -> None:
    name = _dbname(url_or_name)
    if name.endswith("_test"):
        raise DatabaseIsTestError(
            f"refusing to use {name!r}: a *_test database is reset by the test suite"
        )


def provision_schema_and_seed(conn: Connection, tenant_id: str = TENANT_ID) -> None:
    """Migrate to head and seed the default categories and starter rules. Idempotent.

    ``conn`` must be idle (``apply_schema`` manages its own transaction)."""
    apply_schema(conn)
    seed_default_categories(conn, tenant_id)
    seed_starter_rules(conn, tenant_id)
