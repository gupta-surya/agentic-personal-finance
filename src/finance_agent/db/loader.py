"""Database plumbing: the connection type and ``apply_schema``.

Loading data lives in ``finance_agent.ingest``: bronze records the exact bytes of
a pull, a connector-specific normalizer turns them into the source-neutral
contract, and the silver loader persists that.
"""

from importlib.resources import files

import psycopg
from alembic import command
from alembic.config import Config
from psycopg.rows import TupleRow
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

Connection = psycopg.Connection[TupleRow]


class TenantNotProvisionedError(RuntimeError):
    """The tenant has no categories; seed them before loading transactions."""


def apply_schema(conn: Connection) -> None:
    """Migrate the database behind ``conn`` to the latest Alembic revision.

    Alembic runs on ``conn`` itself (not a second connection), so every
    connection parameter (sslmode, options, service, ...) is preserved and there
    is no cross-connection lock wait. ``conn`` must be idle (no open
    transaction); it is switched to non-autocommit for the duration so the
    migration is atomic, then restored. The connection is left open.
    """
    if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        raise RuntimeError("apply_schema needs an idle connection (no open transaction)")
    config = Config()
    config.set_main_option("script_location", str(files("finance_agent.db").joinpath("migrations")))
    engine = create_engine("postgresql+psycopg://", creator=lambda: conn, poolclass=StaticPool)
    was_autocommit = conn.autocommit
    conn.autocommit = False
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        conn.autocommit = was_autocommit
        # No engine.dispose(): that would close the caller's connection.
