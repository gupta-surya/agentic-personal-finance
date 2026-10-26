"""Dev entrypoint: ``uvicorn finance_agent.serve_charts:app``.

The only place that supplies the wall clock (the user's local date) and, for now, the
fake catalog of synthetic data. Chart logic receives both by injection.

Set ``CHARTS_TODAY=YYYY-MM-DD`` to pin "today", e.g. to match the synthetic data's
range (Sep 2025 – Oct 2026) when your real date is later.
"""

import os
from datetime import date, datetime

from finance_agent.charts.api import create_app
from finance_agent.charts.fake_catalog import FakeSeriesCatalog
from finance_agent.charts.templates import default_registry


def local_today() -> date:
    pinned = os.environ.get("CHARTS_TODAY")
    if pinned:
        return date.fromisoformat(pinned)
    return datetime.now().astimezone().date()


app = create_app(default_registry(), FakeSeriesCatalog, local_today)
