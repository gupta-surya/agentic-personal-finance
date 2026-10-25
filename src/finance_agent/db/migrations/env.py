"""Alembic environment: raw-SQL migrations, no SQLAlchemy models.

Two entry points share this file:
- ``apply_schema`` passes a ready SQLAlchemy connection via ``config.attributes``.
- the ``alembic`` CLI builds one from ``DATABASE_URL``.
"""

import os

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()


supplied: Connection | None = context.config.attributes.get("connection")
if supplied is not None:
    _run(supplied)
else:
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as cli_connection:
        _run(cli_connection)
