"""Deterministic categorization from merchant rules. No model, no network.

``categorize`` gives each posted, non-transfer transaction the category of the rule its
merchant key matches: an exact rule first, else the single best fuzzy (trigram) rule at or
above ``FUZZY_THRESHOLD``. Precedence is user > rule > model: a ``user`` row is never
changed, a ``user``-sourced rule may replace ``rule`` and ``model`` rows, and a ``rule``
or ``model`` sourced rule fills only NULL or ``rule`` rows. Writes are guarded so a second
run changes nothing.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from finance_agent.categorize.enrich import normalize_merchant
from finance_agent.db.loader import Connection

FUZZY_THRESHOLD = 0.8
_FLOAT4_SLACK = 1e-6  # pg_trgm's similarity() is a 4-byte float
_TIE = 1e-9


@dataclass(frozen=True)
class Rule:
    key: str  # the normalized merchant the rule is for
    category: str
    source: str  # rule | model | user


@dataclass(frozen=True)
class CategorizeResult:
    assigned: int  # rows that had no category and got one
    changed: int  # rows whose category or source changed
    unchanged: int  # candidate rows left exactly as they were
    uncategorized: int  # candidate rows with no category after the run


def lock_categorization(conn: Connection, tenant_id: str) -> None:
    """Serialize categorization and category decisions for one tenant (transaction-scoped)."""
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"categorize:{tenant_id}",)
    )


def load_rules(conn: Connection, tenant_id: str) -> dict[str, Rule]:
    rows = conn.execute(
        "SELECT merchant_normalized, category, source FROM merchant_rules WHERE tenant_id = %s",
        (tenant_id,),
    ).fetchall()
    return {key: Rule(key, category, source) for key, category, source in rows}


def resolve_merchants(
    conn: Connection,
    tenant_id: str,
    merchants: Iterable[str],
    rules: dict[str, Rule],
    threshold: float | None = None,
) -> dict[str, Rule | None]:
    """The rule each merchant key resolves to: exact first, else the single best fuzzy one.

    A fuzzy match needs similarity >= ``threshold``. If two different rules are equally
    best, the merchant gets no rule: ties are never broken arbitrarily.
    """
    threshold = FUZZY_THRESHOLD if threshold is None else threshold  # read at call time
    wanted = {m for m in merchants if m}
    resolved: dict[str, Rule | None] = {m: rules[m] for m in wanted if m in rules}
    pending = sorted(wanted - set(resolved))
    if pending and rules:
        # `%` is the index-assisted prefilter; the exact >= comparison is done below.
        conn.execute(
            "SELECT set_config('pg_trgm.similarity_threshold', %s, true)",
            (str(max(threshold - 0.05, 0.0)),),
        )
        rows = conn.execute(
            """
            SELECT m.merchant, r.merchant_normalized, similarity(r.merchant_normalized, m.merchant)
            FROM unnest(%s::text[]) AS m(merchant)
            JOIN merchant_rules r ON r.tenant_id = %s AND r.merchant_normalized %% m.merchant
            """,
            (pending, tenant_id),
        ).fetchall()
        scored: dict[str, list[tuple[float, str]]] = defaultdict(list)
        for merchant, key, similarity in rows:
            if similarity + _FLOAT4_SLACK >= threshold:
                scored[merchant].append((float(similarity), key))
        for merchant in pending:
            candidates = scored.get(merchant, [])
            best = max((s for s, _ in candidates), default=None)
            winners = {key for s, key in candidates if best is not None and best - s < _TIE}
            resolved[merchant] = rules[winners.pop()] if len(winners) == 1 else None
    return resolved


def decide(
    current_category: str | None, current_source: str | None, rule: Rule
) -> tuple[str, str] | None:
    """The ``(category, source)`` a row should have under ``rule``, or None to leave it."""
    if current_source == "user":
        return None
    if rule.source == "user":
        replaceable = current_source in (None, "rule", "model")
    else:
        replaceable = current_source in (None, "rule")
    if not replaceable:
        return None
    new_source = "model" if rule.source == "model" else "rule"
    if (current_category, current_source) == (rule.category, new_source):
        return None
    return rule.category, new_source


def categorize(
    conn: Connection, tenant_id: str, threshold: float | None = None
) -> CategorizeResult:
    """Apply the tenant's rules to every posted, non-transfer transaction. Safe to re-run.

    ``threshold`` defaults to the module's ``FUZZY_THRESHOLD`` (read at call time).
    """
    with conn.transaction():
        lock_categorization(conn, tenant_id)
        rows = conn.execute(
            """
            SELECT id, description, merchant_normalized, category, category_source
            FROM transactions
            WHERE tenant_id = %s
              AND NOT pending
              AND posted_date IS NOT NULL
              AND NOT is_internal_transfer
            ORDER BY id
            """,
            (tenant_id,),
        ).fetchall()
        keys = {row[0]: normalize_merchant(row[1]) for row in rows}
        matches = resolve_merchants(
            conn, tenant_id, keys.values(), load_rules(conn, tenant_id), threshold
        )

        key_updates: list[tuple[object, ...]] = []
        category_updates: list[tuple[object, ...]] = []
        assigned = changed = uncategorized = 0
        for txn_id, _, stored_key, category, source in rows:
            key = keys[txn_id] or None
            if stored_key != key:
                key_updates.append((key, tenant_id, txn_id, key))
            rule = matches.get(keys[txn_id]) if key else None
            decision = decide(category, source, rule) if rule else None
            if decision is not None:
                category_updates.append((*decision, tenant_id, txn_id, *decision))
                assigned += category is None
                changed += category is not None
                category = decision[0]
            uncategorized += category is None

        with conn.cursor() as cur:
            if key_updates:
                cur.executemany(
                    "UPDATE transactions SET merchant_normalized = %s "
                    "WHERE tenant_id = %s AND id = %s AND merchant_normalized IS DISTINCT FROM %s",
                    key_updates,
                )
            if category_updates:
                cur.executemany(
                    "UPDATE transactions SET category = %s, category_source = %s "
                    "WHERE tenant_id = %s AND id = %s "
                    "AND category_source IS DISTINCT FROM 'user' "
                    "AND (category, category_source) IS DISTINCT FROM (%s, %s)",
                    category_updates,
                )
        return CategorizeResult(
            assigned=assigned,
            changed=changed,
            unchanged=len(rows) - assigned - changed,
            uncategorized=uncategorized,
        )
