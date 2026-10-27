"""``clarify``: what the planner returns when it cannot choose a chart confidently.

A question and 2 to 4 options. Each option is a ready ``{template_id, params}`` that goes
straight to the render route, so choosing one never involves a model. Options are checked
against the registry here, so a chip can never name a template or parameters that do not
exist. There is no data behind a clarify card: no period, series or sources.
"""

import re
from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from finance_agent.charts.registry import (
    Template,
    TemplateParamsError,
    TemplateRegistry,
    UnknownTemplateError,
)
from finance_agent.charts.spec import ChartSpec, Clarify, ClarifyOption, Table
from finance_agent.queries.series import SeriesCatalog

# A currency symbol or code beside digits, or digits beside a percent sign.
_FIGURE = re.compile(
    r"[$€£]\s*\d|\d\s*(?:%|percent\b)|\d\s*(?:USD|EUR|GBP|dollars?|euros?)\b", re.I
)


class ClarifyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: Literal["clarify"]
    question: str = Field(min_length=1, max_length=300)
    options: list[ClarifyOption] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def _text_states_no_figures(self) -> Self:
        """A question and its labels are model-written text, so they may not state a
        dollar amount or a percentage: such a figure would have no ``result_id``. (Words
        like "last 6 months" are fine. Figures spelled out in words are not detected.)"""
        for text in (self.question, *(option.label for option in self.options)):
            if _FIGURE.search(text):
                raise ValueError("clarify text may not state an amount of money or a percentage")
        return self


def _check_option(index: int, option: ClarifyOption, registry: TemplateRegistry) -> None:
    # The index only: the label is untrusted text and does not belong in error messages.
    where = f"options[{index}]"
    if option.template_id == "clarify":
        raise TemplateParamsError(f"{where}: an option cannot be another clarify question")
    try:
        template = registry.get(option.template_id)
    except UnknownTemplateError:
        raise TemplateParamsError(f"{where}: unknown template {option.template_id!r}") from None
    if option.params.get("template", option.template_id) != option.template_id:
        raise TemplateParamsError(f"{where}: params.template must be {option.template_id!r}")
    try:
        template.params_model.model_validate({**option.params, "template": option.template_id})
    except ValidationError as err:
        first = err.errors(include_url=False, include_context=False, include_input=False)[0]
        field = ".".join(str(part) for part in first["loc"])
        raise TemplateParamsError(f"{where}: bad params at {field}: {first['msg']}") from None


def make_template(registry: TemplateRegistry) -> Template[ClarifyParams]:
    """The template needs the registry to validate its options, so it is built from it."""

    def build(params: ClarifyParams, catalog: SeriesCatalog, today: date) -> ChartSpec:
        for index, option in enumerate(params.options):
            _check_option(index, option, registry)
        return ChartSpec(
            template_id="clarify",
            title=params.question,
            params=params.model_dump(mode="json"),
            period=None,
            series=[],
            sources=[],
            table=Table(columns=[], rows=[]),
            clarify=Clarify(question=params.question, options=params.options),
        )

    return Template("clarify", ClarifyParams, build)
