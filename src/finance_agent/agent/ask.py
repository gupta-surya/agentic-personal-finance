"""Orchestration: plan -> render -> narrate -> verify -> answer.

A fetch of the catalog and the clock are injected (as in the charts API). Any ungrounded
narration is blocked and replaced by the chart's deterministic, grounded title, so no
untraceable number can ever reach the user.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date

from finance_agent.agent.narrate import Narrator
from finance_agent.agent.plan import Planner
from finance_agent.agent.verify import verify
from finance_agent.charts.period import PeriodError
from finance_agent.charts.registry import (
    TemplateParamsError,
    TemplateRegistry,
    UnknownTemplateError,
)
from finance_agent.charts.spec import ChartSpec
from finance_agent.queries.series import SeriesCatalog

Session = Callable[[], AbstractContextManager[SeriesCatalog]]


@dataclass(frozen=True)
class Answer:
    prose: str
    spec: ChartSpec | None
    grounded: bool
    unmatched: list[str]


def answer(
    question: str,
    planner: Planner,
    narrator: Narrator,
    registry: TemplateRegistry,
    session: Session,
    today: Callable[[], date],
) -> Answer:
    plan = planner.plan(question)
    params = plan.params
    try:
        with session() as catalog:
            spec = registry.render(
                params.template, params.model_dump(mode="json"), catalog, today()
            )
    except (UnknownTemplateError, TemplateParamsError, PeriodError, ValueError):
        return Answer("I couldn't find a way to answer that from your data.", None, True, [])

    prose = narrator.narrate(question, spec)
    report = verify(prose, spec)
    if report.ok:
        return Answer(prose, spec, True, [])
    # Ungrounded: block it, fall back to the deterministic title (grounded by construction).
    return Answer(f"{spec.title}.", spec, False, report.unmatched)
