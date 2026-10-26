"""Bronze: the exact bytes of every pull, written before anything is parsed.

Append-only in spirit: the body and its hash never change. Only the processing
outcome (``parse_status``, ``dialect_detected``, ``parse_error``) is filled in
afterwards. A NULL ``parse_status`` means "received, not yet processed", for
example because the tenant wasn't provisioned when the pull arrived.
"""

import hashlib

import psycopg
from psycopg.types.json import Jsonb

from finance_agent.db.loader import Connection
from finance_agent.ingest.contract import RawPull

_INSERT = """
    INSERT INTO raw_pulls (
        tenant_id, source, requested_version, server_versions, request_params,
        http_status, fetched_at, body, body_sha256, body_json
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
    ON CONFLICT (tenant_id, body_sha256) DO NOTHING
    RETURNING id
"""


def _queryable_text(body: bytes) -> str | None:
    """The body as text for the queryable JSON copy, or None if it isn't UTF-8.

    Whether it is valid JSON is Postgres's call (see ``record_pull``), so the body
    is parsed once in Python, by the normalizer.
    """
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return None


def record_pull(conn: Connection, tenant_id: str, pull: RawPull) -> tuple[int, bool]:
    """Store the pull. Returns ``(raw_pull_id, created)``.

    The same bytes for the same tenant dedupe to the existing row (``created`` is
    False), whatever the request parameters were.
    """
    digest = hashlib.sha256(pull.body).hexdigest()

    def insert(body_json: str | None) -> tuple[object, ...] | None:
        return conn.execute(
            _INSERT,
            (
                tenant_id,
                pull.source,
                pull.requested_version,
                Jsonb(pull.server_versions) if pull.server_versions is not None else None,
                Jsonb(pull.request_params),
                pull.http_status,
                pull.fetched_at,
                pull.body,
                digest,
                body_json,
            ),
        ).fetchone()

    with conn.transaction():
        try:
            with conn.transaction():  # savepoint: Postgres can reject JSON that Python accepts
                row = insert(_queryable_text(pull.body))
        except psycopg.errors.DataError:
            row = insert(None)
        if row is not None:
            return int(str(row[0])), True
        existing = conn.execute(
            "SELECT id FROM raw_pulls WHERE tenant_id = %s AND body_sha256 = %s",
            (tenant_id, digest),
        ).fetchone()
        assert existing is not None
        return int(existing[0]), False


def finish_pull(
    conn: Connection,
    tenant_id: str,
    raw_pull_id: int,
    status: str,
    dialect: str | None,
    note: str | None,
) -> None:
    """Record the processing outcome (only when it changed). The stored bytes are never touched."""
    conn.execute(
        """
        UPDATE raw_pulls
        SET parse_status = %s, dialect_detected = %s, parse_error = %s
        WHERE tenant_id = %s AND id = %s
          AND (parse_status, dialect_detected, parse_error) IS DISTINCT FROM (%s, %s, %s)
        """,
        (status, dialect, note, tenant_id, raw_pull_id, status, dialect, note),
    )
