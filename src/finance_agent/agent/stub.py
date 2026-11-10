"""Deterministic stand-ins for the model, so the loop runs with no Ollama (tests and demos).

StubNarrator restates the chart's deterministic title, which is grounded by construction, so
it always passes the verifier. StubPlanner maps a few keywords to a template.
"""

from finance_agent.agent.narrate import Narrator
from finance_agent.agent.plan import Plan, Planner
from finance_agent.charts.period import Period, PeriodPreset
from finance_agent.charts.spec import ChartSpec
from finance_agent.charts.templates.cash_flow import CashFlowParams
from finance_agent.charts.templates.kpi import KpiParams
from finance_agent.charts.templates.spend_breakdown import SpendBreakdownParams
from finance_agent.charts.templates.spend_over_time import SpendOverTimeParams


def _period(preset: PeriodPreset) -> Period:
    return Period(preset=preset)


class StubPlanner(Planner):
    def plan(self, question: str) -> Plan:
        q = question.lower()
        if (
            any(w in q for w in ("where", "break", "biggest", "category", "categories"))
            and "trend" not in q
        ):
            return Plan(
                params=SpendBreakdownParams(
                    template="spend_breakdown", period=_period(PeriodPreset.LAST_MONTH)
                )
            )
        if any(w in q for w in ("cash flow", "saving", "save", "net")):
            return Plan(
                params=CashFlowParams(
                    template="cash_flow", period=_period(PeriodPreset.LAST_3_MONTHS)
                )
            )
        if any(w in q for w in ("trend", "over time")):
            return Plan(
                params=SpendOverTimeParams(
                    template="spend_over_time", period=_period(PeriodPreset.LAST_6_MONTHS)
                )
            )
        if any(w in q for w in ("income", "earn", "made")):
            return Plan(
                params=KpiParams(
                    template="kpi", measure="income", period=_period(PeriodPreset.LAST_MONTH)
                )
            )
        return Plan(
            params=KpiParams(
                template="kpi", measure="spend", period=_period(PeriodPreset.LAST_MONTH)
            )
        )


class StubNarrator(Narrator):
    def narrate(self, question: str, spec: ChartSpec) -> str:
        return f"{spec.title}."
