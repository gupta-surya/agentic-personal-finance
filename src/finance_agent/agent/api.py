"""The agent app: the charts routes plus ``POST /ask``.

The web app talks to one origin for both /charts/* and /ask. The planner is injected, so a
test or demo runs the whole loop with a fake planner and no model.
"""

from collections.abc import Callable
from datetime import date
from typing import Literal

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel, ConfigDict, Field

from finance_agent.agent.ask import Answer, Session, answer
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
    source: Literal["synthetic", "postgres"] = "synthetic",
    ledger: APIRouter | None = None,
) -> FastAPI:
    app = create_app(registry, session, today, source=source, ledger=ledger)

    @app.post("/ask")
    def ask(request: AskRequest) -> dict[str, object]:
        result: Answer = answer(request.question, planner, registry, session, today)
        return {
            "prose": result.prose,
            "grounded": result.grounded,
            "unmatched": result.unmatched,
            "chart_spec": result.spec.model_dump(mode="json") if result.spec else None,
        }

    return app
