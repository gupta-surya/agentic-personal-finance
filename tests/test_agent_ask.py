"""The /ask loop end to end with stubs on the fake catalog (no model, no DB)."""

from datetime import date

from fastapi.testclient import TestClient

from finance_agent.agent.api import create_agent_app
from finance_agent.agent.ask import answer
from finance_agent.agent.narrate import Narrator
from finance_agent.agent.stub import StubNarrator, StubPlanner
from finance_agent.charts.fake_catalog import fake_session
from finance_agent.charts.spec import ChartSpec
from finance_agent.charts.templates import default_registry
from finance_agent.model_gateway.errors import ModelUnavailable

REG = default_registry()


def _today() -> date:
    return date(2026, 10, 25)


def test_every_stub_route_answers_grounded() -> None:
    questions = [
        "how much did I spend last month?",
        "where did my money go?",
        "what's my cash flow?",
        "how much did I earn?",
        "show my spending trend",
    ]
    for q in questions:
        result = answer(q, StubPlanner(), StubNarrator(), REG, fake_session, _today)
        assert result.spec is not None
        assert result.grounded is True
        assert result.prose


class _BadNarrator(Narrator):
    def narrate(self, question: str, spec: ChartSpec) -> str:
        return "You spent $99,999,999.00 somehow."


def test_ungrounded_narration_is_blocked_and_falls_back_to_title() -> None:
    result = answer(
        "how much did I spend?", StubPlanner(), _BadNarrator(), REG, fake_session, _today
    )
    assert result.grounded is False
    assert "$99,999,999.00" in result.unmatched
    assert result.spec is not None
    assert result.prose == f"{result.spec.title}."  # grounded fallback


class _DownPlanner(StubPlanner):
    def plan(self, question: str) -> object:  # type: ignore[override]
        raise ModelUnavailable("model endpoint is down")


def test_model_down_returns_a_clear_message_not_a_crash() -> None:
    result = answer(
        "how much did I spend?",
        _DownPlanner(),
        StubNarrator(),
        REG,
        fake_session,
        _today,
        engine="qwen3:8b",
    )
    assert result.spec is None
    assert result.grounded is True
    assert "ollama" in result.prose.lower()
    assert result.engine == "qwen3:8b"


def test_ask_endpoint_returns_prose_and_chart() -> None:
    app = create_agent_app(
        REG, fake_session, _today, StubPlanner(), StubNarrator(), engine="stub-x"
    )
    client = TestClient(app)
    response = client.post("/ask", json={"question": "where did my money go last month?"})
    assert response.status_code == 200
    body = response.json()
    assert body["grounded"] is True
    assert body["chart_spec"]["template_id"] == "spend_breakdown"
    assert body["prose"]
    assert body["engine"] == "stub-x"
    # The same app still serves the charts routes.
    assert client.get("/charts/meta").json() == {"source": "synthetic"}
