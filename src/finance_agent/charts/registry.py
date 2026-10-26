"""Template registry: ``template_id`` -> params model + deterministic builder.

Each params model has ``template: Literal["<id>"]`` as its first field so the
planner's output can be a discriminated union and the template streams first.
"""

from collections.abc import Callable
from datetime import date
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from finance_agent.charts.spec import ChartSpec, enforce_point_budget
from finance_agent.queries.series import SeriesCatalog

P = TypeVar("P", bound=BaseModel)


class UnknownTemplateError(KeyError):
    """No template is registered under this id."""


class Template(Generic[P]):  # noqa: UP046 - TypeVar keeps mypy strict happy with the registry
    def __init__(
        self,
        template_id: str,
        params_model: type[P],
        build: Callable[[P, SeriesCatalog, date], ChartSpec],
    ) -> None:
        field = params_model.model_fields.get("template")
        if field is None or next(iter(params_model.model_fields)) != "template":
            raise TypeError(f"{params_model.__name__}: 'template' must be the first field")
        self.template_id = template_id
        self.params_model = params_model
        self._build = build

    def render(self, raw_params: dict[str, Any], catalog: SeriesCatalog, today: date) -> ChartSpec:
        if raw_params.get("template", self.template_id) != self.template_id:
            raise ValueError(f"params.template must be {self.template_id!r}")
        params = self.params_model.model_validate({**raw_params, "template": self.template_id})
        spec = self._build(params, catalog, today)
        if spec.template_id != self.template_id:
            raise ValueError(f"builder returned template_id {spec.template_id!r}")
        enforce_point_budget(spec)
        return spec


class TemplateRegistry:
    def __init__(self) -> None:
        self._templates: dict[str, Template[Any]] = {}

    def register(self, template: Template[Any]) -> None:
        if template.template_id in self._templates:
            raise ValueError(f"template {template.template_id!r} is already registered")
        self._templates[template.template_id] = template

    def get(self, template_id: str) -> Template[Any]:
        try:
            return self._templates[template_id]
        except KeyError:
            raise UnknownTemplateError(template_id) from None

    def ids(self) -> list[str]:
        return sorted(self._templates)

    def render(
        self, template_id: str, raw_params: dict[str, Any], catalog: SeriesCatalog, today: date
    ) -> ChartSpec:
        return self.get(template_id).render(raw_params, catalog, today)
