from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

import pytest
from pydantic import BaseModel, ValidationError

from finance_agent.charts.fake_catalog import FakeSeriesCatalog
from finance_agent.charts.period import Period, resolve_period
from finance_agent.charts.registry import Template, TemplateRegistry, UnknownTemplateError
from finance_agent.charts.spec import (
    Annotation,
    Assumption,
    ChartSpec,
    Point,
    PointBudgetError,
    Series,
    SliderControl,
    Source,
    Table,
    enforce_point_budget,
)
from finance_agent.queries.series import SeriesCatalog

TODAY = date(2026, 10, 25)
AS_OF = datetime(2026, 10, 25, 12, tzinfo=UTC)


class EchoParams(BaseModel):
    template: Literal["echo"]
    period: Period


def build_echo(params: EchoParams, catalog: SeriesCatalog, today: date) -> ChartSpec:
    period = resolve_period(params.period, today)
    result = catalog.cash_flow(period.start, period.end, "USD")
    assert result.rows is not None
    source = Source(
        result_id=result.result_id,
        query=result.query,
        data_version=result.data_version,
        as_of=result.as_of,
    )
    return ChartSpec(
        template_id="echo",
        title="Echo",
        params=params.model_dump(mode="json"),
        period=period,
        series=[
            Series(
                id="net",
                kind="line",
                label="Net",
                result_id=result.result_id,
                points=[Point(x=r.month.isoformat(), y=r.net) for r in result.rows],
            )
        ],
        sources=[source],
        table=Table(
            columns=["month", "net"], rows=[[r.month.isoformat(), str(r.net)] for r in result.rows]
        ),
    )


def registry() -> TemplateRegistry:
    reg = TemplateRegistry()
    reg.register(Template("echo", EchoParams, build_echo))
    return reg


def render(params: dict[str, Any] | None = None) -> ChartSpec:
    raw = params or {"period": {"preset": "last_3_months"}}
    return registry().render("echo", raw, FakeSeriesCatalog(), TODAY)


def test_render_is_deterministic_and_money_serializes_as_strings() -> None:
    first, second = render(), render()
    assert first.model_dump_json() == second.model_dump_json()
    dumped = first.model_dump(mode="json")
    first_point = dumped["series"][0]["points"][0]
    assert first_point["x"] == "2026-07-01"
    assert isinstance(first_point["y"], str)  # never a JSON float
    assert dumped["period"]["start"] == "2026-07-01"
    assert dumped["period"]["end"] == "2026-10-01"


def test_planner_never_supplies_template_in_params() -> None:
    assert render().template_id == "echo"
    with pytest.raises(ValueError, match="params.template"):
        render({"template": "other", "period": {"preset": "last_month"}})


def test_unknown_template_and_duplicate_registration() -> None:
    with pytest.raises(UnknownTemplateError):
        registry().get("nope")
    reg = registry()
    with pytest.raises(ValueError, match="already registered"):
        reg.register(Template("echo", EchoParams, build_echo))


def test_invalid_params_raise_validation_error_with_paths() -> None:
    with pytest.raises(ValidationError) as err:
        render({"period": {"preset": "custom"}})
    assert err.value.errors()[0]["loc"][0] == "period"


def test_template_field_must_be_first() -> None:
    class Bad(BaseModel):
        period: Period
        template: Literal["bad"]

    with pytest.raises(TypeError, match="first field"):
        Template("bad", Bad, build_echo)  # type: ignore[arg-type]


def test_series_rejects_floats_and_mismatched_points() -> None:
    with pytest.raises(ValidationError):
        Point(x="a", y=1.5)
    with pytest.raises(ValidationError):
        Series(id="s", kind="line", label="s", result_id="r", points=[Point(x="a")])
    with pytest.raises(ValidationError):
        Series(
            id="s",
            kind="range",
            label="s",
            result_id="r",
            points=[Point(x="a", low=Decimal(5), high=Decimal(1))],
        )
    ok = Series(
        id="s",
        kind="range",
        label="s",
        result_id="r",
        points=[Point(x="a", low=Decimal(1), high=Decimal(5))],
    )
    assert ok.points[0].high == 5


def test_every_cited_result_id_must_be_a_source() -> None:
    spec = render()
    with pytest.raises(ValidationError, match="not listed in sources"):
        spec.model_copy(update={}).model_validate({**spec.model_dump(mode="json"), "sources": []})


def test_annotation_and_control_and_table_validation() -> None:
    with pytest.raises(ValidationError):
        Annotation(kind="reference_line", label="x", result_id="r")
    with pytest.raises(ValidationError):
        Annotation(kind="reference_dot", label="x", result_id="r", x="2026-01")
    with pytest.raises(ValidationError):
        SliderControl(min=Decimal(10), max=Decimal(5), step=Decimal(1))
    with pytest.raises(ValidationError):
        Table(columns=["a", "b"], rows=[["only one"]])
    assert Assumption(key="k", label="K", value="1", source="you_entered").control is None


def test_point_budget_refuses_oversized_series() -> None:
    spec = render()
    big = spec.series[0].model_copy(
        update={"points": [Point(x=str(i), y=Decimal(i)) for i in range(11)]}
    )
    with pytest.raises(PointBudgetError):
        enforce_point_budget(spec.model_copy(update={"series": [big]}), limit=10)
    enforce_point_budget(spec)
