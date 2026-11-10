"""Tool selection: a question -> params for exactly one chart template.

The output schema is a discriminated union of the real template param models, so whatever the
model returns is already valid params for one template (or generation fails). The gateway runs
this as an AGENT_TURN job, which is raw-class and therefore local-only.
"""

from typing import Annotated, Protocol

from pydantic import BaseModel, Field

from finance_agent.charts.templates.cash_flow import CashFlowParams
from finance_agent.charts.templates.category_trends import CategoryTrendsParams
from finance_agent.charts.templates.kpi import KpiParams
from finance_agent.charts.templates.spend_breakdown import SpendBreakdownParams
from finance_agent.charts.templates.spend_over_time import SpendOverTimeParams
from finance_agent.model_gateway.client import ModelGateway
from finance_agent.model_gateway.routing import Job
from finance_agent.model_gateway.structured import Message

PlanParams = Annotated[
    CashFlowParams | SpendOverTimeParams | SpendBreakdownParams | KpiParams | CategoryTrendsParams,
    Field(discriminator="template"),
]


class Plan(BaseModel):
    params: PlanParams


class Planner(Protocol):
    def plan(self, question: str) -> Plan: ...


SYSTEM = """You pick ONE chart to answer a question about the user's own finances.

Templates and when to use each:
- kpi: one number for a period. measure = spend | income | net. "how much did I spend/earn",
  "what was my net". For spend you may set category to narrow to one category.
- cash_flow: income vs spending and the running net over months. "cash flow", "am I saving".
- spend_breakdown: spending split by category (or merchant) for a period. "where did my money
  go", "biggest categories". group_by = category | merchant; top_n up to 12.
- spend_over_time: monthly spending over a period, optionally for chosen categories. "trend".
- category_trends: monthly spend per category over N months (3-12). "which categories rose".

period.preset is one of: this_month, last_month, last_3_months, last_6_months, last_12_months,
year_to_date, last_year, all_time. Use last_month if the question gives no period. Never set
start/end unless preset is custom. Return params for exactly one template."""


class GatewayPlanner:
    def __init__(self, gateway: ModelGateway) -> None:
        self._gateway = gateway

    def plan(self, question: str) -> Plan:
        messages: list[Message] = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": question},
        ]
        return self._gateway.generate(Job.AGENT_TURN, messages, Plan)
