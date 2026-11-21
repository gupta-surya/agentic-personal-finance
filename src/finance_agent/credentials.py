"""The credentials zone: bank access URLs, encrypted, isolated from the data tables.

A credential is ciphertext in its own ``credentials`` table, scoped by ``tenant_id`` and
never joined to connections or accounts. ``get_access_url`` returns ``None`` when the tenant
has no credential: it never falls back to a global value or another tenant's, so one tenant
can never resolve another's bank access. The access URL is bearer-grade (it embeds bank
credentials): encrypted at rest (``crypto``), never logged, never in bronze, never in the
environment.
"""

from datetime import datetime

from finance_agent.crypto import KeyStore, decrypt, encrypt
from finance_agent.db.loader import Connection

ACCESS_URL = "simplefin_access_url"


def store_access_url(
    conn: Connection, tenant_id: str, access_url: str, keystore: KeyStore, now: datetime
) -> None:
    key, key_id = keystore.current_key(tenant_id)
    blob = encrypt(key, access_url)
    conn.execute(
        """
        INSERT INTO credentials (tenant_id, kind, ciphertext, key_id, updated_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (tenant_id, kind) DO UPDATE
            SET ciphertext = EXCLUDED.ciphertext,
                key_id = EXCLUDED.key_id,
                updated_at = EXCLUDED.updated_at
        """,
        (tenant_id, ACCESS_URL, blob, key_id, now),
    )


def get_access_url(conn: Connection, tenant_id: str, keystore: KeyStore) -> str | None:
    row = conn.execute(
        "SELECT ciphertext, key_id FROM credentials WHERE tenant_id = %s AND kind = %s",
        (tenant_id, ACCESS_URL),
    ).fetchone()
    if row is None:
        return None  # no fallback, ever
    ciphertext, key_id = row
    return decrypt(keystore.key_for(tenant_id, str(key_id)), bytes(ciphertext))


def has_access_url(conn: Connection, tenant_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM credentials WHERE tenant_id = %s AND kind = %s",
        (tenant_id, ACCESS_URL),
    ).fetchone()
    return row is not None


def delete_access_url(conn: Connection, tenant_id: str) -> None:
    conn.execute(
        "DELETE FROM credentials WHERE tenant_id = %s AND kind = %s",
        (tenant_id, ACCESS_URL),
    )
