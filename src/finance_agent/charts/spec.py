"""ChartSpec: the typed object the browser draws. Built by deterministic code only.

Money is ``Decimal`` here and a JSON *string* on the wire, so no float ever carries
a dollar amount; the browser converts to numbers for geometry and shows the original
strings in labels. Every series and annotation names the ``result_id`` it came from,
and every such id must appear in ``sources`` so a number can always be traced.
"""

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, JsonValue, model_validator

from finance_agent.charts.period import ResolvedPeriod
from finance_agent.queries.result import Money

MAX_POINTS_PER_SERIES = 5_000  # SVG stays fast below this; the resolver refuses more


class PointBudgetError(ValueError):
    """A spec would ship more points than the renderer can draw quickly."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Source(_Frozen):
    """One query or engine result that backs part of the chart."""

    result_id: str
    query: str
    data_version: str
    as_of: datetime


class Point(_Frozen):
    """``x`` is a label or ISO date/month string. Lines and bars set ``y``; ranges set
    ``low`` and ``high`` instead."""

    x: str
    y: Money | None = None
    low: Money | None = None
    high: Money | None = None


class Series(_Frozen):
    id: str
    kind: Literal["line", "bar", "area", "range", "point"]
    label: str
    result_id: str
    points: list[Point]

    @model_validator(mode="after")
    def _points_match_kind(self) -> Self:
        for point in self.points:
            if self.kind == "range":
                if point.low is None or point.high is None or point.y is not None:
                    raise ValueError(f"series {self.id!r}: range points need low and high only")
                if point.low > point.high:
                    raise ValueError(f"series {self.id!r}: low must not exceed high")
            elif point.y is None or point.low is not None or point.high is not None:
                raise ValueError(f"series {self.id!r}: {self.kind} points need y only")
        return self


class Annotation(_Frozen):
    kind: Literal["reference_line", "reference_dot"]
    label: str
    result_id: str
    x: str | None = None
    y: Money | None = None

    @model_validator(mode="after")
    def _has_position(self) -> Self:
        if self.x is None and self.y is None:
            raise ValueError("annotation needs x, y or both")
        if self.kind == "reference_dot" and (self.x is None or self.y is None):
            raise ValueError("reference_dot needs both x and y")
        return self


class SliderControl(_Frozen):
    type: Literal["slider"] = "slider"
    min: Money
    max: Money
    step: Money

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.min < self.max or self.step <= 0:
            raise ValueError("slider needs min < max and step > 0")
        return self


class Assumption(_Frozen):
    """An input behind a number, shown under the chart; a control makes it adjustable."""

    key: str
    label: str
    value: str
    source: Literal["question", "you_entered", "default", "data"]
    control: SliderControl | None = None


class Table(_Frozen):
    """The same data as the chart, for screen readers and the table toggle."""

    columns: list[str]
    rows: list[list[str | None]]

    @model_validator(mode="after")
    def _rectangular(self) -> Self:
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("every table row must have one cell per column")
        return self


class ClarifyOption(_Frozen):
    """A ready request: choosing it sends ``{template_id, params}`` to the render route."""

    label: str
    template_id: str
    params: dict[str, JsonValue]


class Clarify(_Frozen):
    """A question with 2 to 4 options, for when the planner cannot choose confidently."""

    question: str
    options: list[ClarifyOption]

    @model_validator(mode="after")
    def _two_to_four_options(self) -> Self:
        if not 2 <= len(self.options) <= 4:
            raise ValueError("a clarify question needs 2 to 4 options")
        return self


class ChartSpec(_Frozen):
    template_id: str
    title: str
    params: dict[str, JsonValue]  # the resolved params the chart was built from
    period: ResolvedPeriod | None  # None for a clarify question, which covers no data
    series: list[Series]
    annotations: list[Annotation] = []
    assumptions: list[Assumption] = []
    sources: list[Source]
    table: Table
    clarify: Clarify | None = None  # set only by the clarify template

    @model_validator(mode="after")
    def _every_result_id_is_a_source(self) -> Self:
        known = {source.result_id for source in self.sources}
        cited = {s.result_id for s in self.series} | {a.result_id for a in self.annotations}
        if missing := cited - known:
            raise ValueError(f"result_ids not listed in sources: {sorted(missing)}")
        return self


def enforce_point_budget(spec: ChartSpec, limit: int = MAX_POINTS_PER_SERIES) -> None:
    for series in spec.series:
        if len(series.points) > limit:
            raise PointBudgetError(
                f"series {series.id!r} has {len(series.points)} points; the limit is {limit}"
            )
