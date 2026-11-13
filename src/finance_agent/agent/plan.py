"""Triage + tool selection: decide whether a message is a finance-data question, and if so
which chart answers it.

The model returns one of two shapes (a discriminated union):
- ``Chart``: params for exactly one chart template (valid params by construction).
- ``Reply``: a short conversational reply, for greetings, thanks, or anything not answerable
  from the user's financial data. A reply may state no figure — the verifier blocks any.

Run as the raw-class AGENT_TURN job (local-only).
"""

from typing import Annotated, Literal, Protocol

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


class Chart(BaseModel):
    kind: Literal["chart"]
    params: PlanParams


class Reply(BaseModel):
    kind: Literal["reply"]
    text: str = Field(max_length=400)


PlanResult = Annotated[Chart | Reply, Field(discriminator="kind")]


class Plan(BaseModel):
    result: PlanResult


class Planner(Protocol):
    def plan(self, question: str) -> Plan: ...


SYSTEM = """You answer questions about the user's own finances, or reply conversationally.

First decide what the message is:
- A question about their finances (spending, income, categories, cash flow, trends, "how much
  did I...", "where did my money go", "am I saving") -> return kind "chart".
- A greeting, thanks, small talk, anything NOT about their financial data ("hi", "thanks",
  "who are you", "what's the weather"), OR a finance question none of the templates below can
  show (e.g. net worth, one specific merchant) -> return kind "reply" with a short, friendly
  text. In a reply you have no data, so state NO dollar amount or percentage and give no
  financial advice; say what you can help with instead.

For kind "chart", pick ONE template and fill its params:
- kpi: one number for a period. measure = spend | income | net. For spend you may set category.
- cash_flow: income vs spending and running net over months. "cash flow", "am I saving".
- spend_breakdown: spending split by category (or merchant) for a period. "where did my money go".
- spend_over_time: monthly spending over a period, optionally chosen categories. "trend".
- category_trends: monthly spend per category over N months (3-12). "which categories rose".

period.preset: this_month, last_month, last_3_months, last_6_months, last_12_months,
year_to_date, last_year, all_time. Use last_month if no period is given. Never set start/end
unless preset is custom."""


class GatewayPlanner:
    def __init__(self, gateway: ModelGateway) -> None:
        self._gateway = gateway

    def plan(self, question: str) -> Plan:
        messages: list[Message] = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": question},
        ]
        return self._gateway.generate(Job.AGENT_TURN, messages, Plan)
