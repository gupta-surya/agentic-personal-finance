"""Held-out evaluation on the labeled fixture: how often are the rules right?

Ground truth lives in the fixture (``extra.truth``), not in the code under test. The
protocol is the spec's: seed the starter rules, then play a user who reviews only the
FIRST half of the year and corrects what is wrong or missing (each correction becomes a
rule), then score the SECOND half. A wrong category is worse than none, so precision is
the gate; coverage is reported beside it.
"""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import pytest

from finance_agent.categorize import rules
from finance_agent.categorize.actions import correct_category
from finance_agent.categorize.enrich import normalize_merchant
from finance_agent.categorize.rules import categorize
from finance_agent.categorize.starter_rules import seed_starter_rules
from finance_agent.db.default_categories import DEFAULT_CATEGORIES, seed_default_categories
from finance_agent.db.loader import Connection, apply_schema
from finance_agent.ingest.pipeline import ingest
from tests.helpers import FIXTURES, UTC_TZ, pull_from_text

TENANT = "demo-tenant"
FIXTURE = FIXTURES / "labeled_transactions.json"
SPLIT = date(2026, 7, 1)  # first half = before, second half = on or after
PRECISION_GATE = 0.99


@dataclass(frozen=True)
class Labeled:
    ext_id: str
    description: str
    posted: date
    amount: str
    truth: str | None


def labeled() -> list[Labeled]:
    doc: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [
        Labeled(
            t["id"],
            t["description"],
            datetime.fromtimestamp(t["posted"], tz=UTC).date(),
            t["amount"],
            t["extra"]["truth"],
        )
        for t in doc["accounts"][0]["transactions"]
    ]


@dataclass(frozen=True)
class Score:
    rows: int
    categorized: int
    correct: int

    @property
    def coverage(self) -> float:
        return self.categorized / self.rows if self.rows else 1.0

    @property
    def precision(self) -> float:
        return self.correct / self.categorized if self.categorized else 1.0

    def __str__(self) -> str:
        return (
            f"coverage {self.coverage:6.1%} ({self.categorized}/{self.rows})  "
            f"precision {self.precision:6.1%} ({self.correct}/{self.categorized})"
        )


def categories(conn: Connection, by: str = "external_id") -> dict[str, str | None]:
    """``by`` (external_id or description) -> the category currently assigned."""
    rows = conn.execute(f"SELECT {by}, category FROM transactions").fetchall()  # noqa: S608
    return {r[0]: r[1] for r in rows}


def score(conn: Connection, rows: list[Labeled]) -> Score:
    got = categories(conn)
    categorized = [r for r in rows if got[r.ext_id] is not None]
    correct = [
        r for r in categorized if got[r.ext_id] == r.truth
    ]  # a category on a None truth is wrong
    return Score(len(rows), len(categorized), len(correct))


@dataclass(frozen=True)
class EvalResult:
    starter_second_half: Score
    learned_second_half: Score
    learned_repeat_merchants: Score
    learned_classifiable_repeats: Score  # repeat merchants with a right answer (truth not None)
    corrections: int


def run_eval(conn: Connection, threshold: float | None = None) -> EvalResult:
    rows = labeled()
    first = [r for r in rows if r.posted < SPLIT]
    second = [r for r in rows if r.posted >= SPLIT]
    seen = {normalize_merchant(r.description) for r in first}
    repeat = [r for r in second if normalize_merchant(r.description) in seen]

    result = ingest(conn, TENANT, pull_from_text(FIXTURE.read_bytes()), UTC_TZ)
    assert result.status == "ok", result.message
    ids = {r[0]: r[1] for r in conn.execute("SELECT external_id, id FROM transactions").fetchall()}
    seed_starter_rules(conn, TENANT)
    categorize(conn, TENANT, threshold)
    starter = score(conn, second)

    corrections = 0
    for row in sorted(first, key=lambda r: (r.posted, r.ext_id)):  # the user reviews H1 only
        now = categories(conn)
        if row.truth is not None and now[row.ext_id] != row.truth:
            correct_category(conn, TENANT, ids[row.ext_id], row.truth)
            corrections += 1
    user_rows = {
        r[0]
        for r in conn.execute(
            "SELECT external_id FROM transactions WHERE category_source = 'user'"
        ).fetchall()
    }
    assert user_rows <= {r.ext_id for r in first}, "corrections must come from the first half only"
    classifiable = [r for r in repeat if r.truth is not None]
    return EvalResult(
        starter, score(conn, second), score(conn, repeat), score(conn, classifiable), corrections
    )


def reset(conn: Connection) -> None:
    conn.execute("DROP SCHEMA public CASCADE")
    conn.execute("CREATE SCHEMA public")
    apply_schema(conn)
    seed_default_categories(conn, TENANT)


def test_the_fixture_is_the_labeled_set_the_spec_describes() -> None:
    rows = labeled()
    descriptions = {r.description for r in rows}
    taxonomy = {name for _, name in DEFAULT_CATEGORIES}

    assert len(rows) >= 200
    assert {r.truth for r in rows if r.truth is not None} <= taxonomy
    assert {"SQ *COFFEE 0471", "STARBUCKS #1234", "Starbucks Store 5501"} <= descriptions
    assert any(r.truth is None for r in rows)  # unclassifiable descriptions
    assert any(r.amount.startswith("-") is False and r.truth != "income" for r in rows)  # refunds
    assert not any('"category"' in line for line in FIXTURE.read_text().splitlines())  # no hints
    assert (
        sum(r.posted < SPLIT for r in rows) >= 100 and sum(r.posted >= SPLIT for r in rows) >= 100
    )


def test_rules_meet_the_precision_gate_on_the_held_out_half(
    conn: Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    result = run_eval(conn)

    with capsys.disabled():
        print(f"\n--- held-out evaluation at threshold {rules.FUZZY_THRESHOLD} ---")
        print(f"starter rules alone, second half     {result.starter_second_half}")
        print(f"+ rules learned from first half      {result.learned_second_half}")
        print(f"  ...repeat merchants only           {result.learned_repeat_merchants}")
        print(f"  ...of those, classifiable          {result.learned_classifiable_repeats}")
        print(f"  user corrections used (first half) {result.corrections}")
    assert result.starter_second_half.precision >= PRECISION_GATE
    assert result.learned_second_half.precision >= PRECISION_GATE
    assert result.learned_repeat_merchants.precision >= PRECISION_GATE
    # Every repeat merchant that HAS a right answer is categorized; the rows left blank are
    # exactly the unclassifiable ones, which is correct.
    assert result.learned_classifiable_repeats.coverage == 1.0
    uncategorized_repeats = (
        result.learned_repeat_merchants.rows - result.learned_repeat_merchants.categorized
    )
    assert uncategorized_repeats == sum(
        1 for r in labeled() if r.posted >= SPLIT and r.truth is None
    )


def test_threshold_tuning_table(
    conn: Connection, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    table = []
    for threshold in (0.7, 0.75, 0.8, 0.85, 0.9):
        reset(conn)
        monkeypatch.setattr(rules, "FUZZY_THRESHOLD", threshold)
        table.append((threshold, run_eval(conn)))

    with capsys.disabled():
        print("\n--- fuzzy threshold tuning, all second-half rows (139) ---")
        print("threshold | starter rules alone | + learned (incl. near-names)")
        for threshold, r in table:
            starter, learned = r.starter_second_half, r.learned_second_half
            starter_wrong = starter.categorized - starter.correct
            learned_wrong = learned.categorized - learned.correct
            print(
                f"   {threshold:.2f}   | {starter.categorized:3d} cat, {starter_wrong} wrong "
                f"| {learned.categorized:3d} cat, {learned_wrong} wrong, "
                f"precision {learned.precision:6.2%}"
            )
    by_threshold = dict(table)
    assert by_threshold[0.8].learned_second_half.precision >= PRECISION_GATE
    # The table must be able to tell thresholds apart, or "tuned" would mean nothing.
    assert len({str(r.learned_second_half) for r in by_threshold.values()}) >= 3


# Near-names in the fixture (second half only). The key is the rule they resemble; the
# similarity is what pg_trgm reports.
NEAR_NAMES = {
    # the same merchant, mistyped: right to match
    "GREENLEAF GROCER": 0.824,
    "CORNER MARKETS": 0.812,
    "NORTHSIDE FITNES": 0.842,
    "LUCKY NOODLES": 0.800,
    "RIVERSIDE DENTAL CARE": 0.773,
    "PENN ENERGY AUTOPAYMENT": 0.760,
    "STARBUCK": 0.727,
    # a DIFFERENT merchant with a similar name: wrong to match
    "RIVERSIDE DENTAL SUPPLY": 0.708,
    "CITY WATER PARK": 0.688,
    "CINEPLEX BAR": 0.692,
    "NORTHSIDE FITNESS APPAREL": 0.692,
}
LOOK_ALIKES = {
    "RIVERSIDE DENTAL SUPPLY",
    "CITY WATER PARK",
    "CINEPLEX BAR",
    "NORTHSIDE FITNESS APPAREL",
}


@pytest.mark.parametrize("threshold", [0.7, 0.8, 0.9])
def test_near_names_match_exactly_when_their_similarity_clears_the_threshold(
    conn: Connection, monkeypatch: pytest.MonkeyPatch, threshold: float
) -> None:
    monkeypatch.setattr(rules, "FUZZY_THRESHOLD", threshold)
    run_eval(conn)

    got = categories(conn, "description")
    truth = {r.description: r.truth for r in labeled()}
    matched = {d for d in NEAR_NAMES if got[d] is not None}

    assert matched == {d for d, sim in NEAR_NAMES.items() if sim + 1e-6 >= threshold}
    wrong = {d for d in matched if got[d] != truth[d]}
    # At 0.7 the one look-alike that clears it is (wrongly) categorized; from 0.8 up, none.
    assert wrong == ({"RIVERSIDE DENTAL SUPPLY"} if threshold == 0.7 else set())
    assert not (matched - wrong) & LOOK_ALIKES
