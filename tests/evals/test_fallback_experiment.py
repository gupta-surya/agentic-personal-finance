import json

from finance_agent.categorize.enrich import normalize_merchant
from finance_agent.db.default_categories import DEFAULT_CATEGORIES
from finance_agent.evals import fallback_experiment as fx
from finance_agent.evals.model_benchmark import FIXTURE

NAMES = [n for _, n in DEFAULT_CATEGORIES]


def test_every_default_category_has_a_description_and_examples_name_real_categories() -> None:
    assert set(fx.DESCRIPTIONS) == set(NAMES)
    assert set(fx.EXAMPLES) <= set(NAMES)


def test_example_merchants_are_not_in_the_labeled_fixture_so_the_prompt_cannot_leak_it() -> None:
    txns = json.loads(FIXTURE.read_text())["accounts"][0]["transactions"]
    fixture = {normalize_merchant(t["description"]) for t in txns}
    examples = {normalize_merchant(e) for group in fx.EXAMPLES.values() for e in group}
    assert examples & fixture == set()


def test_prompts_list_the_categories_and_only_the_chosen_extras() -> None:
    plain = fx.system_prompt("plain", NAMES, unsure=False)
    assert all(n in plain for n in NAMES) and fx.DESCRIPTIONS["rent"] not in plain
    assert fx.UNSURE not in plain
    described = fx.system_prompt("described", NAMES, unsure=True)
    assert "- rent: rent or mortgage payments" in described and "e.g." not in described
    assert f"answer {fx.UNSURE}" in described
    assert "(e.g. ALDI, WEGMANS)" in fx.system_prompt("examples", NAMES, unsure=False)
    assert fx.system_prompt("alt", NAMES, False) != fx.system_prompt("described", NAMES, False)


def test_accept_needs_agreement_a_real_category_and_enough_confidence() -> None:
    one = fx.Variant("v", ("plain",), min_confidence=0.9)
    assert fx.accept(one, [("dining", 0.95)]) == "dining"
    assert fx.accept(one, [("dining", 0.89)]) is None
    assert fx.accept(fx.Variant("v", ("plain",), unsure=True), [(fx.UNSURE, 1.0)]) is None
    two = fx.Variant("v", ("described", "alt"))
    assert fx.accept(two, [("dining", 0.1), ("dining", 0.2)]) == "dining"
    assert fx.accept(two, [("dining", 1.0), ("groceries", 1.0)]) is None


def test_score_counts_a_wrongly_accepted_unclassifiable_merchant_and_skips_invalid_replies() -> (
    None
):
    merchants = [("A", "dining"), ("B", "dining"), ("C", None), ("D", None), ("E", "health")]
    answers = {"A": ("dining", 1.0), "B": ("groceries", 1.0), "C": ("other", 1.0), "D": None}

    def ask(merchant: str, kind: str, unsure: bool) -> tuple[str, float] | None:
        return answers.get(merchant, (fx.UNSURE, 1.0))

    s = fx.score(fx.Variant("v", ("plain",), unsure=True), merchants, ask)

    # A right, B wrong, C accepted though unclassifiable (wrong), D invalid, E unsure
    assert (s.asked, s.accepted, s.correct, s.wrong) == (5, 3, 1, 2)
    assert round(s.precision, 4) == 0.3333


def test_the_report_marks_the_bar_and_the_no_answer_case() -> None:
    v = fx.Variant("v", ("plain",))
    report = fx.render(
        [
            (v, fx.Score(10, 10, 10, 1.0)),
            (v, fx.Score(10, 10, 9, 1.0)),
            (v, fx.Score(10, 0, 0, 1.0)),
        ],
        {"model": "m"},
    )
    rows = [line for line in report.splitlines() if line.startswith("| v ")]
    assert [("PASS" in r, "fail" in r) for r in rows] == [
        (True, False),
        (False, True),
        (False, True),
    ]
