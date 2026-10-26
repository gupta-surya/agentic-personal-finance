"""What only the Postgres catalog can be asked: roles, accounts, tenants, versions."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal

from finance_agent.db.default_categories import seed_default_categories
from finance_agent.db.loader import Connection
from finance_agent.ingest.pipeline import ingest
from finance_agent.queries.cash_flow import net_cash_flow
from finance_agent.queries.pg_catalog import PostgresSeriesCatalog
from finance_agent.queries.series import SeriesCatalog
from finance_agent.reconcile.actions import mark_not_transfer, set_account_role
from finance_agent.reconcile.match import reconcile
from tests.catalog_conformance.calls import CALLS, FEBRUARY, FULL, MARCH, invoke
from tests.catalog_conformance.dataset import dataset, to_fake, to_postgres
from tests.helpers import FETCHED_AT, UTC_TZ, pull_from_text

TENANT = "demo-tenant"
MARCH_10 = int(datetime(2026, 3, 10, 12, tzinfo=UTC).timestamp())


def _body(*accounts: tuple[str, str, list[tuple[str, str, str | None]]]) -> str:
    """(account id, currency, [(txn id, amount, category hint)]) -> a v2 body, all on March 10."""
    return json.dumps(
        {
            "errlist": [],
            "connections": [{"conn_id": "C", "name": "Bank"}],
            "accounts": [
                {
                    "id": acct,
                    "name": acct,
                    "conn_id": "C",
                    "currency": currency,
                    "balance": "0",
                    "balance-date": 1774958400,
                    "transactions": [
                        {
                            "id": tid,
                            "posted": MARCH_10,
                            "amount": amount,
                            "description": f"X {tid}",
                            **({"extra": {"category": cat}} if cat else {}),
                        }
                        for tid, amount, cat in txns
                    ],
                }
                for acct, currency, txns in accounts
            ],
        }
    )


def _load(conn: Connection, *accounts: tuple[str, str, list[tuple[str, str, str | None]]]) -> None:
    ingest(conn, TENANT, pull_from_text(_body(*accounts)), UTC_TZ)


def _account_id(conn: Connection, external_id: str) -> int:
    row = conn.execute("SELECT id FROM accounts WHERE external_id = %s", (external_id,)).fetchone()
    assert row is not None
    return int(row[0])


def _spend(catalog: SeriesCatalog, currency: str = "USD") -> Decimal:
    value = catalog.kpi("spend", *MARCH, currency).value
    assert value is not None
    return value


def test_the_catalog_satisfies_the_series_catalog_protocol(conn: Connection) -> None:
    catalog: SeriesCatalog = PostgresSeriesCatalog(conn, TENANT)

    assert catalog.cash_flow(*MARCH, "USD").rows == []


# --- accounts ----------------------------------------------------------------


def test_loan_and_investment_accounts_are_excluded_and_credit_counts(conn: Connection) -> None:
    _load(
        conn,
        ("checking", "USD", [("a", "-10.00", "dining")]),
        ("card", "USD", [("b", "-20.00", "dining")]),
        ("mortgage", "USD", [("c", "-40.00", "dining")]),
        ("brokerage", "USD", [("d", "-80.00", "dining")]),
    )
    catalog = PostgresSeriesCatalog(conn, TENANT)
    assert _spend(catalog) == Decimal("150.00")

    set_account_role(conn, TENANT, _account_id(conn, "card"), "credit")
    set_account_role(conn, TENANT, _account_id(conn, "mortgage"), "loan")
    set_account_role(conn, TENANT, _account_id(conn, "brokerage"), "investment")

    assert _spend(catalog) == Decimal("30.00")  # checking 10 + credit card 20
    assert catalog.cash_flow(*MARCH, "USD").totals["outflow"] == Decimal("30.00")


def test_a_closed_accounts_history_still_counts(conn: Connection) -> None:
    _load(conn, ("old", "USD", [("a", "-10.00", "dining")]))
    conn.execute("UPDATE accounts SET closed = true")

    assert _spend(PostgresSeriesCatalog(conn, TENANT)) == Decimal("10.00")


def test_a_custom_currency_account_is_excluded_from_every_currency(conn: Connection) -> None:
    miles = "https://airline.example/miles"
    _load(
        conn,
        ("usd", "USD", [("a", "-10.00", "dining")]),
        ("miles", miles, [("b", "-99.00", "dining")]),
    )
    catalog = PostgresSeriesCatalog(conn, TENANT)

    assert _spend(catalog) == Decimal("10.00")
    assert _spend(catalog, miles) == Decimal("0")
    assert catalog.cash_flow(*MARCH, miles).rows == []


# --- transfers and user decisions ---------------------------------------------


def test_a_low_confidence_transfer_is_excluded_until_the_user_rejects_it(conn: Connection) -> None:
    catalog = to_postgres(conn, TENANT, dataset())  # the Feb 10 pair has no transfer word
    february = catalog.cash_flow(*FEBRUARY, "USD").rows
    assert february is not None and february[0].inflow == Decimal("3200.00")

    leg = conn.execute(
        "SELECT id FROM transactions WHERE is_internal_transfer AND amount < 0"
    ).fetchone()
    assert leg is not None
    mark_not_transfer(conn, TENANT, int(leg[0]))

    february = catalog.cash_flow(*FEBRUARY, "USD").rows
    assert february is not None
    assert (february[0].inflow, february[0].outflow) == (Decimal("3700.00"), Decimal("2447.05"))


# --- income is a flag ----------------------------------------------------------


def test_a_custom_income_category_counts_as_income_not_spend(conn: Connection) -> None:
    conn.execute(
        "INSERT INTO categories (tenant_id, group_name, name, is_income) "
        "VALUES (%s, 'Work', 'side_gig', true)",
        (TENANT,),
    )
    _load(conn, ("a", "USD", [("pay", "120.00", "side_gig"), ("buy", "-30.00", "dining")]))
    catalog = PostgresSeriesCatalog(conn, TENANT)

    assert catalog.kpi("income", *MARCH, "USD").value == Decimal("120.00")
    assert _spend(catalog) == Decimal("30.00")
    breakdown = catalog.spend_breakdown(*MARCH, "USD").rows
    assert breakdown is not None and [r.group for r in breakdown] == ["dining"]


def test_a_category_named_income_but_not_flagged_is_not_income(conn: Connection) -> None:
    conn.execute("UPDATE categories SET is_income = false WHERE name = 'income'")
    _load(conn, ("a", "USD", [("pay", "120.00", "income")]))
    catalog = PostgresSeriesCatalog(conn, TENANT)

    assert catalog.kpi("income", *MARCH, "USD").value == Decimal("0")
    assert _spend(catalog) == Decimal("-120.00")  # it nets as a credit against spend


# --- tenants -------------------------------------------------------------------


def test_one_tenants_catalog_never_sees_anothers_rows(conn: Connection) -> None:
    seed_default_categories(conn, "other-tenant")
    _load(conn, ("a", "USD", [("x", "-10.00", "dining")]))
    ingest(
        conn,
        "other-tenant",
        pull_from_text(_body(("a", "USD", [("x", "-777.00", "dining")]))),
        UTC_TZ,
    )

    assert _spend(PostgresSeriesCatalog(conn, TENANT)) == Decimal("10.00")
    assert _spend(PostgresSeriesCatalog(conn, "other-tenant")) == Decimal("777.00")
    assert _spend(PostgresSeriesCatalog(conn, "nobody")) == Decimal("0")


# --- read-only, versions and freshness -----------------------------------------


def _versions(conn: Connection) -> dict[str, list[tuple[object, ...]]]:
    tables = (
        "raw_pulls",
        "connections",
        "accounts",
        "transactions",
        "transfer_groups",
        "categories",
    )
    return {
        table: [
            tuple(r) for r in conn.execute(f"SELECT xmin::text FROM {table} ORDER BY 1").fetchall()
        ]
        for table in tables
    }


def test_the_whole_call_matrix_writes_nothing(conn: Connection) -> None:
    catalog = to_postgres(conn, TENANT, dataset())
    before = _versions(conn)

    for call in CALLS:
        invoke(catalog, call)
    catalog.earliest_date()

    assert _versions(conn) == before


def test_data_version_moves_with_decisions_and_not_with_reads(conn: Connection) -> None:
    catalog = to_postgres(conn, TENANT, dataset())
    first = catalog.cash_flow(*MARCH, "USD").data_version
    assert catalog.cash_flow(*MARCH, "USD").data_version == first
    assert catalog.kpi("spend", *MARCH, "USD").data_version == first

    set_account_role(conn, TENANT, _account_id(conn, "euro"), "investment")
    second = catalog.cash_flow(*MARCH, "USD").data_version

    assert second != first and second.startswith("dv_")


def test_as_of_is_the_latest_pulls_fetch_time(conn: Connection) -> None:
    catalog = to_postgres(conn, TENANT, dataset())

    assert catalog.cash_flow(*MARCH, "USD").as_of == FETCHED_AT


def test_postgres_agrees_with_net_cash_flow_and_the_cash_flow_series(conn: Connection) -> None:
    catalog = to_postgres(conn, TENANT, dataset())

    for start, end in (FULL, MARCH, FEBRUARY):
        scalar = net_cash_flow(conn, TENANT, start, end, "USD")
        series = catalog.cash_flow(start, end, "USD")
        assert scalar.totals == series.totals
        assert scalar.value == catalog.kpi("net", start, end, "USD").value


# --- earliest_date -------------------------------------------------------------


def test_earliest_date_matches_the_fake_and_ignores_transfers_and_pending(
    conn: Connection,
) -> None:
    rows = dataset()
    catalog = to_postgres(conn, TENANT, rows)

    assert catalog.earliest_date() == to_fake(rows).earliest_date() == date(2025, 9, 1)


def test_earliest_date_is_none_for_a_tenant_with_no_rows(conn: Connection) -> None:
    assert PostgresSeriesCatalog(conn, TENANT).earliest_date() is None


def test_reconcile_can_run_after_the_catalog_was_built(conn: Connection) -> None:
    catalog = to_postgres(conn, TENANT, dataset())

    assert reconcile(conn, TENANT).unchanged == 1
    assert catalog.cash_flow(*FEBRUARY, "USD").rows is not None
