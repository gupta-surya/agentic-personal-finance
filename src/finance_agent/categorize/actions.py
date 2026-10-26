"""User decisions about categories: corrections become rules.

Every action marks what the user decided as ``user``-sourced, which the engine and a
re-ingest never overwrite. A correction also writes a ``user`` merchant rule, so the same
merchant never needs asking about again.
"""

from finance_agent.categorize.enrich import normalize_merchant
from finance_agent.categorize.rules import (
    categorize,
    load_rules,
    lock_categorization,
    resolve_merchants,
)
from finance_agent.db.loader import Connection


def _require_category(conn: Connection, tenant_id: str, category: str) -> None:
    row = conn.execute(
        "SELECT 1 FROM categories WHERE tenant_id = %s AND name = %s", (tenant_id, category)
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown category {category!r} for tenant {tenant_id!r}")


def _upsert_user_rule(conn: Connection, tenant_id: str, key: str, category: str) -> None:
    conn.execute(
        """
        INSERT INTO merchant_rules (tenant_id, merchant_normalized, category, source)
        VALUES (%s, %s, %s, 'user')
        ON CONFLICT (tenant_id, merchant_normalized) DO UPDATE
            SET category = EXCLUDED.category, source = 'user'
            WHERE (merchant_rules.category, merchant_rules.source)
                IS DISTINCT FROM (EXCLUDED.category, 'user')
        """,
        (tenant_id, key, category),
    )


def correct_category(conn: Connection, tenant_id: str, txn_id: int, category: str) -> None:
    """The user says this transaction is ``category``.

    The row becomes ``user``-sourced, its merchant gets a ``user`` rule, and the engine
    re-runs so the merchant's other rows follow (rows the user set themselves stay). A
    description that normalizes to nothing has no merchant to remember, so only the row is
    set. Works on pending rows too.
    """
    with conn.transaction():
        lock_categorization(conn, tenant_id)
        _require_category(conn, tenant_id, category)
        row = conn.execute(
            "SELECT description FROM transactions WHERE tenant_id = %s AND id = %s",
            (tenant_id, txn_id),
        ).fetchone()
        if row is None:
            raise LookupError(f"no transaction {txn_id} for tenant {tenant_id!r}")
        key = normalize_merchant(row[0])
        conn.execute(
            """
            UPDATE transactions
            SET category = %s, category_source = 'user', merchant_normalized = %s
            WHERE tenant_id = %s AND id = %s
              AND (category, category_source, merchant_normalized)
                  IS DISTINCT FROM (%s, 'user', %s)
            """,
            (category, key or None, tenant_id, txn_id, category, key or None),
        )
        if key:
            _upsert_user_rule(conn, tenant_id, key, category)
        categorize(conn, tenant_id)


def set_rule(conn: Connection, tenant_id: str, merchant: str, category: str) -> None:
    """The user says every transaction from ``merchant`` is ``category``.

    ``merchant`` is normalized first, so a raw statement name works. The engine re-runs so
    existing rows follow.
    """
    with conn.transaction():
        lock_categorization(conn, tenant_id)
        key = normalize_merchant(merchant)
        if not key:
            raise ValueError(f"{merchant!r} does not name a merchant")
        _require_category(conn, tenant_id, category)
        _upsert_user_rule(conn, tenant_id, key, category)
        categorize(conn, tenant_id)


def delete_rule(conn: Connection, tenant_id: str, merchant: str) -> None:
    """Remove a rule. Rows that depended on it and were categorized by a rule go back to
    uncategorized (then any other matching rule applies); rows the user set stay as they are.

    Deleting a starter rule is not remembered: seeding the starter rules again restores it.
    """
    with conn.transaction():
        lock_categorization(conn, tenant_id)
        key = normalize_merchant(merchant)
        rules = load_rules(conn, tenant_id)
        if key not in rules:
            raise LookupError(f"no rule for {merchant!r} in tenant {tenant_id!r}")
        candidates = conn.execute(
            """
            SELECT id, description FROM transactions
            WHERE tenant_id = %s AND category_source = 'rule'
              AND NOT pending AND posted_date IS NOT NULL AND NOT is_internal_transfer
            """,
            (tenant_id,),
        ).fetchall()
        merchants = {txn_id: normalize_merchant(desc) for txn_id, desc in candidates}
        resolved = resolve_merchants(conn, tenant_id, merchants.values(), rules)
        dependent = [
            txn_id
            for txn_id, m in merchants.items()
            if (rule := resolved.get(m)) is not None and rule.key == key
        ]
        conn.execute(
            "DELETE FROM merchant_rules WHERE tenant_id = %s AND merchant_normalized = %s",
            (tenant_id, key),
        )
        conn.execute(
            """
            UPDATE transactions SET category = NULL, category_source = NULL
            WHERE tenant_id = %s AND id = ANY(%s) AND category_source = 'rule'
            """,
            (tenant_id, dependent),
        )
        categorize(conn, tenant_id)
