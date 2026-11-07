"""Dev entrypoint: ``uvicorn finance_agent.serve_charts:app --host 127.0.0.1``.

The only place that reads the environment and the wall clock (the user's local date).
Chart logic receives both by injection.

- No ``CHARTS_DATABASE_URL``: serves the fake catalog of synthetic data.
- ``CHARTS_DATABASE_URL`` + ``CHARTS_TENANT_ID``: serves that tenant's data from Postgres,
  read-only. A ``*_test`` database is refused.

Set ``CHARTS_TODAY=YYYY-MM-DD`` to pin "today", e.g. to match the synthetic data's range
(Sep 2025 – Oct 2026) when your real date is later.
"""

import os
from datetime import date, datetime
from functools import partial

from fastapi import FastAPI

from finance_agent.charts.api import create_app
from finance_agent.charts.fake_catalog import fake_session
from finance_agent.charts.postgres import check_database_url, postgres_session
from finance_agent.charts.templates import default_registry


def local_today() -> date:
    pinned = os.environ.get("CHARTS_TODAY")
    if pinned:
        return date.fromisoformat(pinned)
    return datetime.now().astimezone().date()


def build_app() -> FastAPI:
    url = os.environ.get("CHARTS_DATABASE_URL")
    if not url:
        return create_app(default_registry(), fake_session, local_today)
    tenant = os.environ.get("CHARTS_TENANT_ID")
    if not tenant:
        raise RuntimeError("CHARTS_TENANT_ID is required when CHARTS_DATABASE_URL is set")
    check_database_url(url)
    return create_app(
        default_registry(), partial(postgres_session, url, tenant), local_today, source="postgres"
    )


app = build_app()
