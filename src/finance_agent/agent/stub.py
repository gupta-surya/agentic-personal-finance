"""Deterministic stand-ins for the model, so the loop runs with no Ollama (tests and demos).

StubPlanner triages on finance keywords: a message with none is answered conversationally (no
chart); otherwise it maps a keyword to a template. StubNarrator restates the chart's
deterministic title, which is grounded by construction, so it always passes the verifier.
"""

from finance_agent.agent.narrate import Narrator
from finance_agent.agent.plan import Chart, Plan, Planner, PlanParams, Reply
from finance_agent.charts.period import Period, PeriodPreset
from finance_agent.charts.spec import ChartSpec
from finance_agent.charts.templates.cash_flow import CashFlowParams
from finance_agent.charts.templates.kpi import KpiParams
from finance_agent.charts.templates.spend_breakdown import SpendBreakdownParams
from finance_agent.charts.templates.spend_over_time import SpendOverTimeParams

_FINANCE = (
    "spend",
    "spent",
    "spending",
    "money",
    "cash",
    "income",
    "earn",
    "made",
    "budget",
    "categor",
    "net ",
    "save",
    "saving",
    "cost",
    "transaction",
    "$",
    "dollar",
    "expense",
    "bill",
    "trend",
    "where did",
    "how much",
)
_GREETING = (
    "Hi! I can answer questions about your spending, income, categories, and cash flow. "
    'Try "Where did my money go last month?"'
)


def _period(preset: PeriodPreset) -> Period:
    return Period(preset=preset)


def _chart_for(question: str) -> PlanParams:
    q = question.lower()
    if (
        any(w in q for w in ("where", "break", "biggest", "category", "categories"))
        and "trend" not in q
    ):
        return SpendBreakdownParams(
            template="spend_breakdown", period=_period(PeriodPreset.LAST_MONTH)
        )
    if any(w in q for w in ("cash flow", "saving", "save", "net")):
        return CashFlowParams(template="cash_flow", period=_period(PeriodPreset.LAST_3_MONTHS))
    if any(w in q for w in ("trend", "over time")):
        return SpendOverTimeParams(
            template="spend_over_time", period=_period(PeriodPreset.LAST_6_MONTHS)
        )
    if any(w in q for w in ("income", "earn", "made")):
        return KpiParams(template="kpi", measure="income", period=_period(PeriodPreset.LAST_MONTH))
    return KpiParams(template="kpi", measure="spend", period=_period(PeriodPreset.LAST_MONTH))


class StubPlanner(Planner):
    def plan(self, question: str) -> Plan:
        if not any(word in question.lower() for word in _FINANCE):
            return Plan(result=Reply(kind="reply", text=_GREETING))
        return Plan(result=Chart(kind="chart", params=_chart_for(question)))


class StubNarrator(Narrator):
    def narrate(self, question: str, spec: ChartSpec) -> str:
        return f"{spec.title}."
