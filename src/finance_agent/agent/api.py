"""The agent app: the charts routes plus ``POST /ask``.

The web app talks to one origin for both /charts/* and /ask. The planner and narrator are
injected, so a demo or test can run the whole loop with stubs and no model.
"""

from collections.abc import Callable
from datetime import date
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field

from finance_agent.agent.ask import Answer, Session, answer
from finance_agent.agent.narrate import Narrator
from finance_agent.agent.plan import Planner
from finance_agent.charts.api import create_app
from finance_agent.charts.registry import TemplateRegistry


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=500)


def create_agent_app(
    registry: TemplateRegistry,
    session: Session,
    today: Callable[[], date],
    planner: Planner,
    narrator: Narrator,
    source: Literal["synthetic", "postgres"] = "synthetic",
    engine: str = "stub",
) -> FastAPI:
    app = create_app(registry, session, today, source=source)

    @app.post("/ask")
    def ask(request: AskRequest) -> dict[str, object]:
        result: Answer = answer(
            request.question, planner, narrator, registry, session, today, engine
        )
        return {
            "prose": result.prose,
            "grounded": result.grounded,
            "unmatched": result.unmatched,
            "engine": result.engine,
            "chart_spec": result.spec.model_dump(mode="json") if result.spec else None,
        }

    return app
