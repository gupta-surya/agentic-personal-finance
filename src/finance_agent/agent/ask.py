"""Orchestration: one model call decides reply-or-chart, then render and answer.

The planner's single call returns either a conversational reply (no chart) or a chart plan.
A chart's answer sentence is its deterministic, grounded title — there is no second model
call. A conversational reply may state no figure: the verifier blocks any and falls back to a
safe redirect. So every turn is at most one model call, and nothing forces a chart.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date

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
_REDIRECT = "I can help with your spending, income, categories and cash flow — ask me one of those."
_NO_FIT = "I couldn't find a way to answer that from your data."


@dataclass(frozen=True)
class Answer:
    prose: str
    spec: ChartSpec | None
    grounded: bool
    unmatched: list[str]


def answer(
    question: str,
    planner: Planner,
    registry: TemplateRegistry,
    session: Session,
    today: Callable[[], date],
) -> Answer:
    try:
        plan = planner.plan(question)
    except ModelGatewayError:
        return Answer(_MODEL_DOWN, None, True, [])

    result = plan.result
    if isinstance(result, Reply):
        report = verify(result.text, None)  # a conversational reply may state no figure
        if report.ok:
            return Answer(result.text, None, True, [])
        return Answer(_REDIRECT, None, False, report.unmatched)

    assert isinstance(result, Chart)
    try:
        with session() as catalog:
            spec = registry.render(
                result.params.template, result.params.model_dump(mode="json"), catalog, today()
            )
    except (UnknownTemplateError, TemplateParamsError, PeriodError, ValueError):
        return Answer(_NO_FIT, None, True, [])

    # The title is built deterministically from the query result: grounded, no second call.
    return Answer(f"{spec.title}.", spec, True, [])
