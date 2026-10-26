"""Envelope metadata shared by queries: how fresh the data is, and a version of it."""

from datetime import UTC, datetime

from finance_agent.db.loader import Connection

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def data_stamp(conn: Connection, tenant_id: str) -> tuple[str, datetime]:
    """``(data_version, as_of)`` for a tenant.

    ``as_of`` is the fetch time of the latest pull (the Unix epoch if there is none).
    ``data_version`` is opaque: it changes whenever something that can change a query
    result changes (a new pull, a reconcile, a user decision, an account role or a
    category's income flag), so a cached result can be recognised as stale.
    """
    row = conn.execute(
        """
        SELECT
            (SELECT max(fetched_at) FROM raw_pulls WHERE tenant_id = %(t)s),
            md5(concat_ws('|',
                (SELECT coalesce(max(id), 0) FROM raw_pulls WHERE tenant_id = %(t)s),
                (SELECT coalesce(max(id), 0) FROM transfer_groups WHERE tenant_id = %(t)s),
                (SELECT count(*) FROM transfer_groups WHERE tenant_id = %(t)s),
                (SELECT count(*) FROM transactions
                 WHERE tenant_id = %(t)s AND is_internal_transfer),
                (SELECT count(*) FROM transactions
                 WHERE tenant_id = %(t)s AND transfer_source = 'user'),
                (SELECT coalesce(max(last_changed_at)::text, '') FROM transactions
                 WHERE tenant_id = %(t)s),
                (SELECT coalesce(
                    string_agg(role || role_source || closed::text, ',' ORDER BY id), '')
                 FROM accounts WHERE tenant_id = %(t)s),
                (SELECT coalesce(string_agg(name || is_income::text, ',' ORDER BY id), '')
                 FROM categories WHERE tenant_id = %(t)s)
            ))
        """,
        {"t": tenant_id},
    ).fetchone()
    assert row is not None
    return f"dv_{row[1][:12]}", row[0] or _EPOCH
