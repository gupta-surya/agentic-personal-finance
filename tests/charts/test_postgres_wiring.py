"""The chart API over Postgres: same charts as the fake, read-only, no secrets in errors."""

from collections.abc import Iterator
from contextlib import nullcontext
from datetime import date
from functools import partial
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from finance_agent import serve_charts
from finance_agent.charts.api import CatalogUnavailable, create_app
from finance_agent.charts.fake_catalog import FakeSeriesCatalog
from finance_agent.charts.postgres import check_database_url, postgres_session
from finance_agent.charts.templates import default_registry
from finance_agent.db.loader import Connection
from finance_agent.queries.pg_catalog import PostgresSeriesCatalog
from tests.catalog_conformance.dataset import dataset, to_fake, to_postgres
from tests.helpers import database_url

TENANT = "demo-tenant"
TODAY = date(2026, 11, 15)
FULL = {"preset": "custom", "start": "2025-09-01", "end": "2026-11-01"}

# One request per template, over the whole dataset, so every figure is exercised.
REQUESTS: list[tuple[str, dict[str, Any]]] = [
    ("cash_flow", {"period": FULL}),
    ("spend_over_time", {"period": FULL}),
    ("spend_breakdown", {"period": FULL}),
    ("kpi", {"period": FULL, "measure": "net"}),
    ("kpi", {"period": FULL, "measure": "spend", "category": "groceries"}),
]


@pytest.fixture
def seeded(conn: Connection) -> PostgresSeriesCatalog:
    return to_postgres(conn, TENANT, dataset())


def pg_client() -> TestClient:
    session = partial(postgres_session, database_url(), TENANT)
    return TestClient(create_app(default_registry(), session, lambda: TODAY, source="postgres"))


def fake_client() -> TestClient:
    session = lambda: nullcontext(to_fake(dataset()))  # noqa: E731
    return TestClient(create_app(default_registry(), session, lambda: TODAY))


def post(client: TestClient, template_id: str, params: dict[str, Any]) -> Any:
    return client.post("/charts/render", json={"template_id": template_id, "params": params})


def comparable(body: dict[str, Any]) -> dict[str, Any]:
    """A chart minus its per-execution identity (result ids, freshness), which differs by design."""
    body = {k: v for k, v in body.items() if k != "sources"}
    body["series"] = [{k: v for k, v in s.items() if k != "result_id"} for s in body["series"]]
    return body


@pytest.mark.parametrize(("template_id", "params"), REQUESTS)
def test_every_template_draws_the_same_chart_from_postgres_as_from_the_fake(
    seeded: PostgresSeriesCatalog, template_id: str, params: dict[str, Any]
) -> None:
    from_pg = post(pg_client(), template_id, params)
    from_fake = post(fake_client(), template_id, params)

    assert from_pg.status_code == from_fake.status_code == 200
    assert comparable(from_pg.json()) == comparable(from_fake.json())
    assert from_pg.json()["series"], f"{template_id} drew nothing: the comparison proves little"


def test_figures_are_the_catalogs_own_rows(seeded: PostgresSeriesCatalog) -> None:
    body = post(pg_client(), "cash_flow", {"period": FULL}).json()
    direct = seeded.cash_flow(date(2025, 9, 1), date(2026, 11, 1), "USD")

    assert direct.rows is not None
    net = next(s for s in body["series"] if s["id"] == "net")
    assert [p["y"] for p in net["points"]] == [str(r.net) for r in direct.rows]
    assert [s["query"] for s in body["sources"]] == ["cash_flow", "running_net"]
    assert body["sources"][0]["data_version"] == direct.data_version


def test_all_time_starts_at_the_first_posted_date_on_both_catalogs(
    seeded: PostgresSeriesCatalog,
) -> None:
    for client in (pg_client(), fake_client()):
        response = post(client, "cash_flow", {"period": {"preset": "all_time"}})
        assert response.status_code == 200
        assert response.json()["period"]["start"] == "2025-09-01"


def test_all_time_with_no_history_is_an_empty_chart_not_an_error() -> None:
    client = TestClient(
        create_app(default_registry(), lambda: nullcontext(FakeSeriesCatalog([])), lambda: TODAY)
    )
    response = post(client, "cash_flow", {"period": {"preset": "all_time"}})

    assert response.status_code == 200
    assert response.json()["series"] == []


def test_the_request_connection_is_read_only_and_closed_afterwards(
    seeded: PostgresSeriesCatalog,
) -> None:
    with postgres_session(database_url(), TENANT) as catalog:
        connection = catalog._conn  # noqa: SLF001 - the point is to try a write through it
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            connection.execute("UPDATE categories SET name = name")
        assert not connection.closed
    assert connection.closed


def test_an_unreachable_database_is_a_503_that_leaks_nothing() -> None:
    url = "postgresql://finance:S3CRET-pw@127.0.0.1:1/finance_dev"
    client = TestClient(
        create_app(default_registry(), partial(postgres_session, url, TENANT), lambda: TODAY)
    )
    response = post(client, "cash_flow", {"period": FULL})

    assert response.status_code == 503
    assert response.json() == {"detail": "The database is unavailable."}
    assert "S3CRET" not in response.text and "127.0.0.1" not in response.text


def test_meta_says_which_data_it_is_serving() -> None:
    assert pg_client().get("/charts/meta").json() == {"source": "postgres"}
    assert fake_client().get("/charts/meta").json() == {"source": "synthetic"}


@pytest.mark.parametrize("name", ["finance_test", "finance_ui_test", "x_test"])
def test_a_test_database_is_refused_by_name_without_echoing_the_url(name: str) -> None:
    with pytest.raises(ValueError, match="non-test database") as err:
        check_database_url(f"postgresql://finance:S3CRET-pw@127.0.0.1:5432/{name}")
    assert "S3CRET" not in str(err.value) and name in str(err.value)


def test_the_test_database_guard_ignores_case() -> None:
    with pytest.raises(ValueError, match="non-test database"):
        check_database_url("postgresql://finance:pw@127.0.0.1:5432/Finance_TEST")


def test_a_dev_database_and_a_url_without_a_name() -> None:
    check_database_url("postgresql://finance:pw@127.0.0.1:5432/finance_dev")  # accepted
    with pytest.raises(ValueError):
        check_database_url("postgresql://finance:pw@127.0.0.1:5432")  # no PGDATABASE fallback


def test_a_malformed_url_is_refused_without_echoing_any_of_it() -> None:
    with pytest.raises(ValueError, match="not a valid connection URL") as err:
        check_database_url("host=127.0.0.1 password=S3CRET-pw this-is-not-conninfo")
    assert "S3CRET" not in str(err.value)


def test_a_connection_failure_is_unavailable_but_a_failing_query_stays_a_loud_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def dropped(*_args: object, **_kwargs: object) -> None:
        raise psycopg.InterfaceError("the connection is closed: password=S3CRET-pw")

    with monkeypatch.context() as patch:
        patch.setattr("finance_agent.charts.postgres.psycopg.connect", dropped)
        with pytest.raises(CatalogUnavailable) as err, postgres_session("unused", TENANT):
            pass
    assert "S3CRET" not in str(err.value) and err.value.__cause__ is None

    # a query bug is not "unavailable": it must surface, not be dressed up as an outage
    with pytest.raises(psycopg.ProgrammingError), postgres_session(database_url(), TENANT):
        raise psycopg.ProgrammingError("a bug in a query")


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    monkeypatch.delenv("CHARTS_DATABASE_URL", raising=False)
    monkeypatch.delenv("CHARTS_TENANT_ID", raising=False)
    yield monkeypatch


def test_without_a_database_url_the_app_serves_synthetic_data(env: pytest.MonkeyPatch) -> None:
    client = TestClient(serve_charts.build_app())

    assert client.get("/charts/meta").json() == {"source": "synthetic"}
    assert post(client, "cash_flow", {"period": {"preset": "last_3_months"}}).status_code == 200


def test_a_database_url_needs_a_tenant_and_a_non_test_database(env: pytest.MonkeyPatch) -> None:
    secret_url = "postgresql://finance:S3CRET-pw@127.0.0.1:5432/finance_dev"
    env.setenv("CHARTS_DATABASE_URL", secret_url)
    with pytest.raises(RuntimeError, match="CHARTS_TENANT_ID") as no_tenant:
        serve_charts.build_app()
    assert "S3CRET" not in str(no_tenant.value)

    env.setenv("CHARTS_TENANT_ID", TENANT)
    env.setenv("CHARTS_DATABASE_URL", "postgresql://finance:S3CRET-pw@127.0.0.1:5432/finance_test")
    with pytest.raises(ValueError, match="non-test database") as test_db:
        serve_charts.build_app()
    assert "S3CRET" not in str(test_db.value)

    env.setenv("CHARTS_DATABASE_URL", secret_url)
    app = serve_charts.build_app()  # builds without connecting: a connection is per request
    assert TestClient(app).get("/charts/meta").json() == {"source": "postgres"}
