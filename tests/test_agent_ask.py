"""The /ask loop with an in-test FakePlanner on the fake catalog (no model, no DB)."""

from datetime import date

from fastapi.testclient import TestClient

from finance_agent.agent.api import create_agent_app
from finance_agent.agent.ask import answer
from finance_agent.agent.plan import Chart, Plan, Planner, PlanResult, Reply
from finance_agent.charts.fake_catalog import fake_session
from finance_agent.charts.period import Period, PeriodPreset
from finance_agent.charts.templates import default_registry
from finance_agent.charts.templates.kpi import KpiParams
from finance_agent.charts.templates.spend_breakdown import SpendBreakdownParams
from finance_agent.model_gateway.errors import ModelUnavailable

REG = default_registry()


def _today() -> date:
    return date(2026, 10, 25)


class FakePlanner(Planner):
    """Returns a canned plan, or raises a canned error. No model."""

    def __init__(self, result: PlanResult | Exception) -> None:
        self._result = result

    def plan(self, question: str) -> Plan:
        if isinstance(self._result, Exception):
            raise self._result
        return Plan(result=self._result)


def _chart(params: KpiParams | SpendBreakdownParams) -> Chart:
    return Chart(kind="chart", params=params)


def _last_month() -> Period:
    return Period(preset=PeriodPreset.LAST_MONTH)


def test_chart_plan_answers_with_the_grounded_title() -> None:
    planner = FakePlanner(
        _chart(SpendBreakdownParams(template="spend_breakdown", period=_last_month()))
    )
    result = answer("where did my money go?", planner, REG, fake_session, _today)
    assert result.spec is not None
    assert result.grounded is True
    assert result.prose == f"{result.spec.title}."  # the title is the answer; no second call


def test_reply_plan_answers_conversationally_with_no_chart() -> None:
    planner = FakePlanner(Reply(kind="reply", text="Hi! Ask me about your spending or cash flow."))
    result = answer("hi there", planner, REG, fake_session, _today)
    assert result.spec is None
    assert result.grounded is True
    assert "spending" in result.prose.lower()


def test_a_reply_cannot_state_a_figure() -> None:
    planner = FakePlanner(Reply(kind="reply", text="You have $5,000.00 saved."))
    result = answer("hello", planner, REG, fake_session, _today)
    assert result.spec is None
    assert result.grounded is False
    assert "$5,000.00" not in result.prose  # blocked, redirected


def test_model_down_returns_a_clear_message_not_a_crash() -> None:
    planner = FakePlanner(ModelUnavailable("endpoint is down"))
    result = answer("how much did I spend?", planner, REG, fake_session, _today)
    assert result.spec is None
    assert "ollama" in result.prose.lower()


def test_ask_endpoint_chart_and_greeting() -> None:
    chart_app = create_agent_app(
        REG,
        fake_session,
        _today,
        FakePlanner(_chart(KpiParams(template="kpi", period=_last_month()))),
    )
    client = TestClient(chart_app)
    body = client.post("/ask", json={"question": "how much did I spend?"}).json()
    assert body["chart_spec"]["template_id"] == "kpi"
    assert body["prose"]
    assert client.get("/charts/meta").json() == {"source": "synthetic"}

    greet_app = create_agent_app(
        REG, fake_session, _today, FakePlanner(Reply(kind="reply", text="Hi!"))
    )
    greeting = TestClient(greet_app).post("/ask", json={"question": "hi"}).json()
    assert greeting["chart_spec"] is None
    assert greeting["prose"] == "Hi!"
