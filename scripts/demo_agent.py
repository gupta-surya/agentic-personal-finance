"""Serve the agent on synthetic data with a stub model (no Ollama, no Postgres).

For local demos and the Playwright check: `python scripts/demo_agent.py` then open the web app.
"""

from datetime import date

from fastapi import FastAPI

from finance_agent.agent.api import create_agent_app
from finance_agent.agent.stub import StubNarrator, StubPlanner
from finance_agent.charts.fake_catalog import fake_session
from finance_agent.charts.templates import default_registry


def build_app() -> FastAPI:
    return create_agent_app(
        default_registry(), fake_session, lambda: date(2026, 10, 25), StubPlanner(), StubNarrator()
    )


app = build_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
