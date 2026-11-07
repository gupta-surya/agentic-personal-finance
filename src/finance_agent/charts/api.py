"""``POST /charts/render``: ``{template_id, params}`` -> ``ChartSpec``. No model call.

Powers sliders, suggestion chips and dashboard cards. The catalog session and the clock
are injected, so this module never reads the wall clock and never sees a connection;
``create_app`` is the one place they are supplied.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from finance_agent.charts.period import PeriodError
from finance_agent.charts.registry import (
    TemplateParamsError,
    TemplateRegistry,
    UnknownTemplateError,
)
from finance_agent.charts.spec import ChartSpec, PointBudgetError
from finance_agent.queries.series import SeriesCatalog

# One request's catalog; leaving the block releases whatever it holds (a connection).
Session = Callable[[], AbstractContextManager[SeriesCatalog]]


class CatalogUnavailable(Exception):
    """The data source cannot be reached. Carries no detail: it becomes a 503 with a fixed
    message, so a connection string or password can never reach a response."""


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str
    params: dict[str, Any] = Field(default_factory=dict)


def create_app(
    registry: TemplateRegistry,
    session: Session,
    today: Callable[[], date],
    source: Literal["synthetic", "postgres"] = "synthetic",
) -> FastAPI:
    """``session`` opens one catalog per request; ``today`` is read once per request;
    ``source`` is reported by ``GET /charts/meta`` so the UI can say which data it shows."""
    app = FastAPI(title="Finance Agent charts", version="0.1.0")

    @app.get("/charts/meta")
    def meta() -> dict[str, str]:
        return {"source": source}

    @app.post("/charts/render")
    def render_chart(request: RenderRequest) -> ChartSpec:
        try:
            with session() as catalog:
                return registry.render(request.template_id, request.params, catalog, today())
        except UnknownTemplateError:
            raise HTTPException(404, f"unknown template {request.template_id!r}") from None
        except ValidationError as err:
            detail = [
                {"loc": ["params", *map(str, e["loc"])], "msg": e["msg"]}
                for e in err.errors(include_url=False, include_context=False, include_input=False)
            ]
            raise HTTPException(422, detail) from None
        except (PeriodError, PointBudgetError, TemplateParamsError) as err:
            raise HTTPException(422, str(err)) from None
        except CatalogUnavailable:
            raise HTTPException(503, "The database is unavailable.") from None

    return app
