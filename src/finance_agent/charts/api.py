"""``POST /charts/render``: ``{template_id, params}`` -> ``ChartSpec``. No model call.

Powers sliders, suggestion chips and dashboard cards. The catalog and the clock are
injected, so this module never reads the wall clock and never sees a connection;
``create_app`` is the one place they are supplied.
"""

from collections.abc import Callable
from datetime import date
from typing import Any

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


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str
    params: dict[str, Any] = Field(default_factory=dict)


def create_app(
    registry: TemplateRegistry,
    catalog: Callable[[], SeriesCatalog],
    today: Callable[[], date],
) -> FastAPI:
    """``catalog`` builds one catalog per request; ``today`` is read once per request."""
    app = FastAPI(title="Finance Agent charts", version="0.1.0")

    @app.post("/charts/render")
    def render_chart(request: RenderRequest) -> ChartSpec:
        try:
            return registry.render(request.template_id, request.params, catalog(), today())
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

    return app
