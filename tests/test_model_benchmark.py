import json
from datetime import UTC, datetime
from typing import Any

import pytest

from finance_agent.db.default_categories import DEFAULT_CATEGORIES
from finance_agent.evals import model_benchmark as bench
from finance_agent.model_gateway import ModelGateway
from finance_agent.model_gateway.transport import Response
from tests.model_gateway_helpers import LOCAL, FakeTransport, ok

NAMES = [n for _, n in DEFAULT_CATEGORIES]


def fixture_rows() -> list[tuple[str, str | None, bool]]:
    txns = json.loads(bench.FIXTURE.read_text())["accounts"][0]["transactions"]
    return [
        (
            t["description"],
            t["extra"]["truth"],
            datetime.fromtimestamp(t["posted"], UTC).date() < bench.SPLIT,
        )
        for t in txns
    ]


def truth_by_text() -> dict[str, str | None]:
    from finance_agent.categorize.enrich import normalize_merchant

    out: dict[str, str | None] = {}
    for desc, truth, _ in fixture_rows():
        out[normalize_merchant(desc)] = truth
        out[desc] = truth
    return out


def perfect_model(wrong_for: set[str] | None = None, garbage_for: set[str] | None = None):  # type: ignore[no-untyped-def]
    truths = truth_by_text()

    def reply(payload: dict[str, Any]) -> Response:
        user = payload["messages"][1]["content"]
        text = user.removeprefix("<untrusted_merchant>").removesuffix("</untrusted_merchant>")
        if garbage_for and text in garbage_for:
            return ok("nope")
        truth = truths.get(text)
        if wrong_for and text in wrong_for:
            return ok('{"category": "other", "confidence": 0.9}')
        if truth is None:
            return ok('{"category": "other", "confidence": 0.4}')
        return ok(json.dumps({"category": truth, "confidence": 0.9}))

    return reply


def run(fake: FakeTransport, n: int = 100) -> tuple[list[bench.Outcome], str]:
    prompts = bench.load_prompts("tune", n)
    outcomes, _ = bench.run(ModelGateway(LOCAL, fake), prompts, NAMES)
    return outcomes, bench.render_report(outcomes, 10.0, {"model": "fake"})


def test_the_prompt_pool_is_100_distinct_first_half_prompts_normalized_merchants_first() -> None:
    prompts = bench.load_prompts("tune", 100)

    assert len(prompts) == 100
    assert len({(p.kind, p.text) for p in prompts}) == 100
    assert [p.kind for p in prompts[:58]] == ["normalized"] * 58
    assert all(p.kind == "raw" for p in prompts[58:])


def test_the_tune_split_never_contains_a_holdout_only_description() -> None:
    first = {d for d, _, is_first in fixture_rows() if is_first}
    holdout_only = {d for d, _, is_first in fixture_rows() if not is_first} - first
    assert holdout_only  # the fixture really has some
    assert {p.text for p in bench.load_prompts("tune", 10_000)}.isdisjoint(holdout_only)


def test_a_perfect_model_reports_100_of_100_valid_and_the_exact_curve() -> None:
    outcomes, report = run(FakeTransport(perfect_model()))

    assert sum(o.valid for o in outcomes) == 100
    assert "- schema-valid: 100/100" in report
    assert "| 0.50 | 50/50 | 100.0% | 50 | 100.0% | 0 |" in report
    assert "| 0.90 | 50/50 | 100.0% | 50 | 100.0% | 0 |" in report
    assert "| 0.95 | 0/50 | 0.0% | 0 | n/a | 0 |" in report
    assert "| 0.90 to 1.00 | 50 | 50 | 100.0% |" in report


def test_wrong_answers_and_invalid_replies_are_counted_not_hidden() -> None:
    prompts = bench.load_prompts("tune", 100)
    classifiable = [
        p.text for p in prompts if p.kind == "normalized" and p.truth not in (None, "other")
    ]
    wrong, garbage = {classifiable[0]}, {classifiable[1]}

    outcomes, report = run(FakeTransport(perfect_model(wrong, garbage)))

    assert sum(o.valid for o in outcomes) == 99
    assert "- schema-valid: 99/100" in report
    # 50 classifiable asked, one reply invalid (not covered), one wrong among the 48 covered
    assert bench.accuracy_at(outcomes, 0.5) == (49, 49, 48, 0)
    assert "| 0.50 | 49/49 | 100.0% | 48 | 98.0% | 0 |" in report


def test_an_unclassifiable_merchant_accepted_with_confidence_is_reported() -> None:
    def reply(payload: dict[str, Any]) -> Response:
        return ok('{"category": "other", "confidence": 0.9}')

    outcomes, _ = run(FakeTransport(reply))
    unclassifiable = sum(
        1 for o in outcomes if o.prompt.kind == "normalized" and o.prompt.truth is None
    )
    assert unclassifiable > 0
    assert bench.accuracy_at(outcomes, 0.9)[3] == unclassifiable


@pytest.mark.parametrize("argv", [["--final"], ["--threshold", "0.8"]])
def test_the_holdout_needs_an_explicit_final_run_at_a_chosen_threshold(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exit_:
        bench.main(argv)
    assert exit_.value.code == 2


def test_the_choice_schema_constrains_the_category_to_the_given_names() -> None:
    schema = bench.choice_schema(["a", "b"]).model_json_schema()
    assert schema["$defs"]["Category"]["enum"] == ["a", "b"]
    assert schema["properties"]["confidence"]["maximum"] == 1.0
