"""A small starter set of merchant rules, so a new tenant's first sync is not all blank.

About 30 common US brands. Each key is the normalized form of the brand's usual statement
name (``normalize_merchant``), so a store number or reference after the name is fine but a
longer descriptor (``WHOLE FOODS MARKET``) is a different merchant until the user teaches
it. Brands that span categories (Amazon, Target, Walmart, Costco, Apple) are left out on
purpose: a wrong default is worse than none.

The rules are seeded with ``source='rule'``, so a user's correction for the same merchant
replaces them and a re-seed never overwrites that correction.
"""

from dataclasses import dataclass

from finance_agent.db.loader import Connection

STARTER_RULES: tuple[tuple[str, str], ...] = (
    ("KROGER", "groceries"),
    ("SAFEWAY", "groceries"),
    ("WHOLE FOODS", "groceries"),
    ("TRADER JOES", "groceries"),
    ("PUBLIX", "groceries"),
    ("STARBUCKS", "dining"),
    ("MCDONALDS", "dining"),
    ("CHIPOTLE", "dining"),
    ("SUBWAY", "dining"),
    ("DUNKIN", "dining"),
    ("DOMINOS", "dining"),
    ("PANERA BREAD", "dining"),
    ("SHELL", "transport"),
    ("CHEVRON", "transport"),
    ("EXXONMOBIL", "transport"),
    ("UBER", "transport"),
    ("LYFT", "transport"),
    ("NETFLIX", "subscriptions"),
    ("SPOTIFY", "subscriptions"),
    ("HULU", "subscriptions"),
    ("DISNEY PLUS", "subscriptions"),
    ("XFINITY", "utilities"),
    ("VERIZON", "utilities"),
    ("ATT", "utilities"),
    ("CVS PHARMACY", "health"),
    ("WALGREENS", "health"),
    ("HOME DEPOT", "shopping"),
    ("BEST BUY", "shopping"),
    ("DELTA AIR LINES", "travel"),
    ("AIRBNB", "travel"),
)


@dataclass(frozen=True)
class StarterSeedResult:
    inserted: int
    skipped_unknown_category: int  # rules whose category this tenant does not have


def seed_starter_rules(conn: Connection, tenant_id: str) -> StarterSeedResult:
    """Insert the starter rules for a tenant. Idempotent; never overwrites an existing rule.

    Call it next to ``seed_default_categories`` (the rules need those categories). A rule
    whose category the tenant lacks is skipped and counted.
    """
    inserted = skipped = 0
    with conn.transaction():
        known = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM categories WHERE tenant_id = %s", (tenant_id,)
            ).fetchall()
        }
        for key, category in STARTER_RULES:
            if category not in known:
                skipped += 1
                continue
            cursor = conn.execute(
                """
                INSERT INTO merchant_rules (tenant_id, merchant_normalized, category, source)
                VALUES (%s, %s, %s, 'rule')
                ON CONFLICT (tenant_id, merchant_normalized) DO NOTHING
                """,
                (tenant_id, key, category),
            )
            inserted += cursor.rowcount
    return StarterSeedResult(inserted=inserted, skipped_unknown_category=skipped)
