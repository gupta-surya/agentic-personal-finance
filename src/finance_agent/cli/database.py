"""Create and reach the one local database.

Manages the Docker Postgres for the DB service and creates a dedicated login role plus a
database it owns, with a random password kept in the local 0600 config (never in the
environment or the repo). The developer ``*_test`` database and its throwaway credentials
are untouched, and real use refuses any ``*_test`` name.
"""

import secrets
import string
from collections.abc import Callable

from psycopg import sql

from finance_agent.db.loader import Connection
from finance_agent.provision import guard_not_test_db

APP_DB = "finance"
APP_ROLE = "finance_app"
# The compose superuser, used only to create the app role/db; never stored.
ADMIN_URL = "postgresql://finance:finance@127.0.0.1:5432/postgres"

Runner = Callable[[list[str]], tuple[int, str]]


def random_password(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def app_database_url(
    password: str,
    *,
    host: str = "127.0.0.1",
    port: int = 5432,
    database: str = APP_DB,
    role: str = APP_ROLE,
) -> str:
    return f"postgresql://{role}:{password}@{host}:{port}/{database}"


def compose_up_db(runner: Runner) -> tuple[int, str]:
    """Start just the DB service, detached. The compose file binds it to 127.0.0.1."""
    return runner(["docker", "compose", "up", "-d", "db"])


def ensure_role_and_database(
    admin_conn: Connection, *, database: str = APP_DB, role: str = APP_ROLE, password: str
) -> None:
    """Create (or re-password) the login role and create the database it owns. Idempotent.

    ``admin_conn`` must be autocommit (CREATE DATABASE cannot run in a transaction). Refuses a
    ``*_test`` database so the suite's throwaway database is never adopted for real use.
    """
    guard_not_test_db(database)
    role_exists = admin_conn.execute(
        "SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)
    ).fetchone()
    verb = "ALTER" if role_exists else "CREATE"
    admin_conn.execute(
        sql.SQL("{} ROLE {} WITH LOGIN PASSWORD {}").format(
            sql.SQL(verb), sql.Identifier(role), sql.Literal(password)
        )
    )
    db_exists = admin_conn.execute(
        "SELECT 1 FROM pg_database WHERE datname = %s", (database,)
    ).fetchone()
    if not db_exists:
        admin_conn.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(database), sql.Identifier(role)
            )
        )
