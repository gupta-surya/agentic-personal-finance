"""Orchestration: plan -> render -> narrate -> verify -> answer.

A fetch of the catalog and the clock are injected (as in the charts API). Any ungrounded
narration is blocked and replaced by the chart's deterministic, grounded title, so no
untraceable number can ever reach the user. ``engine`` names what answered (the local model,
or the stub), so the UI can show it and nobody wonders whether the model ran.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date

from finance_agent.agent.narrate import Narrator
from finance_agent.agent.plan import Chart, Planner, Reply
from finance_agent.agent.verify import verify
from finance_agent.charts.period import PeriodError
from finance_agent.charts.registry import (
    TemplateParamsError,
    TemplateRegistry,
    UnknownTemplateError,
)
from finance_agent.charts.spec import ChartSpec
from finance_agent.model_gateway.errors import ModelGatewayError
from finance_agent.queries.series import SeriesCatalog

Session = Callable[[], AbstractContextManager[SeriesCatalog]]

_MODEL_DOWN = "The local model isn't reachable. Start it with `ollama serve` and pull the model."
_REDIRECT = (
    "I can help with your spending, income, categories and cash flow — ask me about one of those."
)


@dataclass(frozen=True)
class Answer:
    prose: str
    spec: ChartSpec | None
    grounded: bool
    unmatched: list[str]
    engine: str


def answer(
    question: str,
    planner: Planner,
    narrator: Narrator,
    registry: TemplateRegistry,
    session: Session,
    today: Callable[[], date],
    engine: str = "stub",
) -> Answer:
    try:
        plan = planner.plan(question)
    except ModelGatewayError:
        return Answer(_MODEL_DOWN, None, True, [], engine)

    result = plan.result
    if isinstance(result, Reply):
        report = verify(result.text, None)
        text = result.text if report.ok else _REDIRECT
        return Answer(text, None, True, [], engine)

    assert isinstance(result, Chart)
    params = result.params
    try:
        with session() as catalog:
            spec = registry.render(
                params.template, params.model_dump(mode="json"), catalog, today()
            )
    except (UnknownTemplateError, TemplateParamsError, PeriodError, ValueError):
        return Answer(
            "I couldn't find a way to answer that from your data.", None, True, [], engine
        )

    try:
        prose = narrator.narrate(question, spec)
    except ModelGatewayError:
        # The chart is computed; fall back to its grounded title rather than failing.
        return Answer(f"{spec.title}.", spec, True, [], engine)

    report = verify(prose, spec)
    if report.ok:
        return Answer(prose, spec, True, [], engine)
    # Ungrounded: block it, fall back to the deterministic title (grounded by construction).
    return Answer(f"{spec.title}.", spec, False, report.unmatched, engine)
