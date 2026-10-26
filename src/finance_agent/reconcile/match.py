"""Transfer reconciliation: find the two legs of a transfer between the user's own accounts.

Pure code, no model. Two posted rows pair when they are in different accounts, in the
same currency, have exactly opposite amounts, and posted within ``WINDOW_DAYS`` of each
other. Nearest date wins; a leg with two equally near partners is ambiguous and nothing
is matched for it. No description keyword is required (wallets and banks word transfers
inconsistently): a match with no transfer word on either leg is stored with
``match_confidence='low'`` so it can be reviewed.

``reconcile`` recomputes the whole matching and diffs it against the groups the engine
made earlier, so it is idempotent, dissolves rule groups that stopped being valid, and
never touches a row a user decided (``transfer_source = 'user'``).
"""

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from psycopg.types.json import Jsonb

from finance_agent.db.loader import Connection

WINDOW_DAYS = 7
RULE_NAME = "nearest_date_exact_amount_v1"
TRANSFER_KEYWORDS = ("TRANSFER", "XFER", "PAYMENT", "AUTOPAY", "ONLINE PMT")


@dataclass(frozen=True)
class Leg:
    """One posted transaction that could be half of a transfer."""

    txn_id: int
    account_id: int
    currency: str
    amount: Decimal
    posted: date
    description: str


@dataclass(frozen=True)
class Pair:
    out_leg: Leg  # the debit (negative amount)
    in_leg: Leg  # the credit (positive amount)
    gap_days: int
    keyword: str | None

    @property
    def confidence(self) -> str:
        return "high" if self.keyword else "low"

    @property
    def key(self) -> frozenset[int]:
        return frozenset({self.out_leg.txn_id, self.in_leg.txn_id})

    def evidence(self) -> dict[str, Any]:
        return {
            "transaction_ids": [self.out_leg.txn_id, self.in_leg.txn_id],
            "amount": format(abs(self.out_leg.amount), "f"),
            "gap_days": self.gap_days,
            "keyword": self.keyword,
            "window_days": WINDOW_DAYS,
        }


@dataclass(frozen=True)
class Pairing:
    pairs: list[Pair]
    ambiguous_legs: frozenset[int]


@dataclass(frozen=True)
class ReconcileResult:
    matched: int  # new groups created this run
    matched_low: int  # of those, how many are low confidence
    updated: int  # existing groups whose confidence or evidence changed
    dissolved: int  # rule groups removed because they stopped being valid
    unchanged: int  # existing rule groups left exactly as they were
    ambiguous: int  # legs left unmatched because two partners were equally near


def matched_keyword(*descriptions: str) -> str | None:
    """The first transfer keyword found in any description (case-insensitive), else None."""
    upper = [d.upper() for d in descriptions]
    for keyword in TRANSFER_KEYWORDS:
        if any(keyword in d for d in upper):
            return keyword
    return None


def pair_legs(legs: Sequence[Leg], window_days: int = WINDOW_DAYS) -> Pairing:
    """Pair opposite legs by smallest date gap. Pure and deterministic.

    Within each (currency, absolute amount) bucket, candidate pairs are taken in order
    of increasing gap. At a given gap, a leg that appears in more than one candidate
    pair is a tie: every leg touched by a tied pair is blocked from matching at all
    (it must not fall back to a farther partner), and the tied legs are reported.
    """
    buckets: dict[tuple[str, Decimal], list[Leg]] = defaultdict(list)
    for leg in legs:
        if leg.amount != 0:
            buckets[(leg.currency, abs(leg.amount))].append(leg)

    pairs: list[Pair] = []
    ambiguous: set[int] = set()
    for key in sorted(buckets):
        bucket = sorted(buckets[key], key=lambda leg: leg.txn_id)
        outs = [leg for leg in bucket if leg.amount < 0]
        ins = [leg for leg in bucket if leg.amount > 0]
        candidates = [
            (abs((o.posted - i.posted).days), o, i)
            for o in outs
            for i in ins
            if o.account_id != i.account_id and abs((o.posted - i.posted).days) <= window_days
        ]
        used: set[int] = set()
        for gap in sorted({c[0] for c in candidates}):
            level = [
                (o, i)
                for g, o, i in candidates
                if g == gap and o.txn_id not in used and i.txn_id not in used
            ]
            degree = Counter(leg.txn_id for o, i in level for leg in (o, i))
            tied = {txn_id for txn_id, count in degree.items() if count > 1}
            ambiguous |= tied
            for o, i in level:
                used |= {o.txn_id, i.txn_id}  # tied legs are blocked, not just skipped
                if o.txn_id not in tied and i.txn_id not in tied:
                    pairs.append(Pair(o, i, gap, matched_keyword(o.description, i.description)))
    pairs.sort(key=lambda p: sorted(p.key))
    return Pairing(pairs, frozenset(ambiguous))


def _candidate_legs(conn: Connection, tenant_id: str) -> list[Leg]:
    rows = conn.execute(
        """
        SELECT t.id, t.account_id, a.currency, t.amount, t.posted_date, t.description
        FROM transactions t
        JOIN accounts a ON a.tenant_id = t.tenant_id AND a.id = t.account_id
        WHERE t.tenant_id = %s
          AND NOT t.pending
          AND t.posted_date IS NOT NULL
          AND a.currency_kind = 'iso'
          AND (t.transfer_source IS NULL OR t.transfer_source = 'rule')
        ORDER BY t.id
        """,
        (tenant_id,),
    ).fetchall()
    return [Leg(*row) for row in rows]


def _rule_groups(
    conn: Connection, tenant_id: str
) -> dict[frozenset[int], tuple[int, str, dict[str, Any]]]:
    """Existing engine-made groups: leg ids -> (group id, confidence, evidence)."""
    rows = conn.execute(
        """
        SELECT g.id, g.match_confidence, g.evidence, array_agg(t.id)
        FROM transfer_groups g
        JOIN transactions t ON t.tenant_id = g.tenant_id AND t.transfer_group_id = g.id
        WHERE g.tenant_id = %s AND g.source = 'rule'
        GROUP BY g.id, g.match_confidence, g.evidence
        """,
        (tenant_id,),
    ).fetchall()
    return {frozenset(txn_ids): (gid, conf, ev) for gid, conf, ev, txn_ids in rows}


def dissolve_group(conn: Connection, tenant_id: str, group_id: int) -> None:
    conn.execute(
        """
        UPDATE transactions
        SET transfer_group_id = NULL, is_internal_transfer = false, transfer_source = NULL
        WHERE tenant_id = %s AND transfer_group_id = %s
        """,
        (tenant_id, group_id),
    )
    conn.execute(
        "DELETE FROM transfer_groups WHERE tenant_id = %s AND id = %s", (tenant_id, group_id)
    )


def lock_tenant(conn: Connection, tenant_id: str) -> None:
    """Serialize reconciliation and transfer decisions for one tenant.

    A transaction-scoped advisory lock: ``reconcile`` and every user action take it first,
    so ``reconcile`` can never read candidates, have a user decide one of them, and then
    write over that decision. The lock is released when the transaction ends.
    """
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (tenant_id,))


def reconcile(conn: Connection, tenant_id: str) -> ReconcileResult:
    """Match transfer legs for a tenant. One database transaction; safe to re-run."""
    with conn.transaction():
        lock_tenant(conn, tenant_id)
        pairing = pair_legs(_candidate_legs(conn, tenant_id))
        existing = _rule_groups(conn, tenant_id)
        desired = {pair.key: pair for pair in pairing.pairs}

        dissolved = 0
        for key, (group_id, _, _) in existing.items():
            if key not in desired:
                dissolve_group(conn, tenant_id, group_id)
                dissolved += 1

        matched = matched_low = updated = unchanged = 0
        for key, pair in desired.items():
            if key in existing:
                group_id, confidence, evidence = existing[key]
                if (confidence, evidence) == (pair.confidence, pair.evidence()):
                    unchanged += 1
                else:
                    conn.execute(
                        "UPDATE transfer_groups SET match_confidence = %s, evidence = %s "
                        "WHERE tenant_id = %s AND id = %s",
                        (pair.confidence, Jsonb(pair.evidence()), tenant_id, group_id),
                    )
                    updated += 1
                continue
            row = conn.execute(
                """
                INSERT INTO transfer_groups (
                    tenant_id, rule, window_days, evidence, source, match_confidence
                )
                VALUES (%s, %s, %s, %s, 'rule', %s)
                RETURNING id
                """,
                (tenant_id, RULE_NAME, WINDOW_DAYS, Jsonb(pair.evidence()), pair.confidence),
            ).fetchone()
            assert row is not None
            conn.execute(
                """
                UPDATE transactions
                SET transfer_group_id = %s, is_internal_transfer = true, transfer_source = 'rule'
                WHERE tenant_id = %s AND id = ANY(%s)
                  AND (transfer_source IS NULL OR transfer_source = 'rule')
                """,
                (row[0], tenant_id, [pair.out_leg.txn_id, pair.in_leg.txn_id]),
            )
            matched += 1
            matched_low += pair.confidence == "low"
        return ReconcileResult(
            matched=matched,
            matched_low=matched_low,
            updated=updated,
            dissolved=dissolved,
            unchanged=unchanged,
            ambiguous=len(pairing.ambiguous_legs),
        )
