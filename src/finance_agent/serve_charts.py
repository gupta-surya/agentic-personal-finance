"""Dev entrypoint: ``uvicorn finance_agent.serve_charts:app``.

The only place that supplies the wall clock (the user's local date) and, for now, the
fake catalog. Chart logic receives both by injection.
"""

from datetime import date, datetime

from finance_agent.charts.api import create_app
from finance_agent.charts.fake_catalog import FakeSeriesCatalog
from finance_agent.charts.registry import TemplateRegistry


def local_today() -> date:
    return datetime.now().astimezone().date()


app = create_app(TemplateRegistry(), FakeSeriesCatalog, local_today)
