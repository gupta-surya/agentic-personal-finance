"""Default category taxonomy: small on purpose (nearer 16 than 104).

Fewer, clearer categories are more accurate to assign. Each tenant gets its own
copy via ``seed_default_categories`` and may add more; the rules engine and the
model prompt both read the tenant's rows, never this constant.
"""

from finance_agent.db.loader import Connection

# (group, name)
DEFAULT_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("Income", "income"),
    ("Housing", "rent"),
    ("Housing", "utilities"),
    ("Food", "groceries"),
    ("Food", "dining"),
    ("Transport", "transport"),
    ("Health", "health"),
    ("Shopping", "shopping"),
    ("Lifestyle", "entertainment"),
    ("Lifestyle", "travel"),
    ("Lifestyle", "subscriptions"),
    ("Financial", "fees_interest"),
    ("Financial", "savings_investments"),
    ("Personal", "education"),
    ("Personal", "gifts_donations"),
    ("Other", "other"),
)


# Categories that count as income. Income is a flag on the row, set at seed time and
# editable by the user afterwards; nothing infers it from a name later.
INCOME_CATEGORIES = frozenset({"income"})


def seed_default_categories(conn: Connection, tenant_id: str) -> None:
    """Insert the default taxonomy for a tenant. Idempotent; never touches existing rows."""
    with conn.transaction():
        for group_name, name in DEFAULT_CATEGORIES:
            conn.execute(
                """
                INSERT INTO categories (tenant_id, group_name, name, is_income)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (tenant_id, name) DO NOTHING
                """,
                (tenant_id, group_name, name, name in INCOME_CATEGORIES),
            )
