"""Schema + seed provisioning (needs Postgres: `docker compose up -d`)."""

from finance_agent.db.loader import Connection
from finance_agent.provision import provision_schema_and_seed


def test_seed_is_idempotent_and_populates_taxonomy(conn: Connection) -> None:
    # conn already applied the schema and seeded demo-tenant; re-seeding a fresh tenant works.
    provision_schema_and_seed(conn, "local")
    categories = conn.execute(
        "SELECT count(*) FROM categories WHERE tenant_id = %s", ("local",)
    ).fetchone()
    rules = conn.execute(
        "SELECT count(*) FROM merchant_rules WHERE tenant_id = %s", ("local",)
    ).fetchone()
    assert categories is not None and categories[0] >= 16
    assert rules is not None and rules[0] > 0

    # Idempotent: a second provision changes nothing and does not raise.
    provision_schema_and_seed(conn, "local")
    again = conn.execute(
        "SELECT count(*) FROM categories WHERE tenant_id = %s", ("local",)
    ).fetchone()
    assert again is not None and again[0] == categories[0]
