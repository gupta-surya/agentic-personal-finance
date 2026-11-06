"""Classification order and net_cash_flow, checked against hand-calculated fixture totals."""

import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from finance_agent.db.loader import Connection
from finance_agent.ingest.pipeline import ingest
from finance_agent.queries.cash_flow import net_cash_flow
from finance_agent.queries.result import QueryResult, ScalarRow
from finance_agent.reconcile.actions import mark_not_transfer, set_account_role
from finance_agent.reconcile.classify import Kind, classify
from finance_agent.reconcile.match import reconcile
from tests.helpers import FIXTURES, UTC_TZ, ingest_file, pull_from_text

TENANT = "demo-tenant"
MARCH = (date(2026, 3, 1), date(2026, 4, 1))


def _flow(conn: Connection, start: date = MARCH[0], end: date = MARCH[1]) -> tuple[str, str, str]:
    result = net_cash_flow(conn, TENANT, start, end, "USD")
    assert result.rows is None and result.value is not None
    totals = result.totals
    assert result.value == totals["net"]
    return str(totals["inflow"]), str(totals["outflow"]), str(totals["net"])


def _id(conn: Connection, external_id: str) -> int:
    row = conn.execute(
        "SELECT id FROM transactions WHERE external_id = %s", (external_id,)
    ).fetchone()
    assert row is not None
    return int(row[0])


def _reconciled(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_transfers.json")
    mark_not_transfer(conn, TENANT, _id(conn, "t08"))  # fixture row 8: the user's override
    reconcile(conn, TENANT)


# --- classification (pure) -------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "transfer", "category", "income", "expected"),
    [
        ("-50.00", True, "groceries", False, Kind.TRANSFER),  # transfer beats a category
        ("3200.00", True, "income", True, Kind.TRANSFER),  # ...and beats the income flag
        ("3200.00", False, "income", True, Kind.INCOME),
        ("120.00", False, "side_gig", True, Kind.INCOME),  # a custom income category
        ("-30.00", False, "groceries", False, Kind.EXPENSE),
        ("-30.00", False, None, False, Kind.EXPENSE),
        ("20.00", False, "groceries", False, Kind.CREDIT),  # a refund
        ("75.00", False, None, False, Kind.UNCATEGORIZED_INFLOW),
        ("0.00", False, None, False, Kind.EXPENSE),
        ("0.00", False, "groceries", False, Kind.EXPENSE),
    ],
)
def test_classification_order(
    amount: str, transfer: bool, category: str | None, income: bool, expected: Kind
) -> None:
    kind = classify(
        Decimal(amount),
        is_internal_transfer=transfer,
        category=category,
        category_is_income=income,
    )

    assert kind is expected


def test_the_income_flag_matters_not_the_name() -> None:
    named_income = classify(
        Decimal("10"), is_internal_transfer=False, category="income", category_is_income=False
    )
    flagged = classify(
        Decimal("10"), is_internal_transfer=False, category="odd_name", category_is_income=True
    )

    assert named_income is Kind.CREDIT
    assert flagged is Kind.INCOME


# --- net_cash_flow over the fixture ---------------------------------------


def test_without_reconciliation_transfers_inflate_both_sides_but_not_the_net(
    conn: Connection,
) -> None:
    ingest_file(conn, TENANT, "simplefin_transfers.json")

    assert _flow(conn) == ("5715.00", "4247.05", "1467.95")


def test_net_cash_flow_matches_the_hand_calculated_totals(conn: Connection) -> None:
    _reconciled(conn)

    assert _flow(conn) == ("4075.00", "2607.05", "1467.95")


def test_the_envelope_is_complete_and_money_is_exact_in_json(conn: Connection) -> None:
    _reconciled(conn)

    result = net_cash_flow(conn, TENANT, *MARCH, "USD")

    assert result.query == "net_cash_flow"
    assert result.params == {"start": "2026-03-01", "end": "2026-04-01", "currency": "USD"}
    assert result.value == Decimal("1467.95")
    payload = json.loads(result.model_dump_json())
    assert payload["totals"] == {"inflow": "4075.00", "outflow": "2607.05", "net": "1467.95"}
    assert payload["value"] == "1467.95" and payload["rows"] is None
    assert len(result.result_id) == 32 and result.data_version.startswith("dv_")
    assert result.as_of.tzinfo is not None and "Internal transfers" in result.amounts_in


def test_a_low_confidence_match_is_excluded_until_the_user_rejects_it(conn: Connection) -> None:
    _reconciled(conn)
    assert _flow(conn)[0] == "4075.00"  # the 40.00 wallet cash-out is netted out

    mark_not_transfer(conn, TENANT, _id(conn, "w11"))

    assert _flow(conn) == ("4115.00", "2647.05", "1467.95")  # +40 in, -40 out, net unchanged


def test_rejecting_a_high_confidence_match_returns_both_legs(conn: Connection) -> None:
    _reconciled(conn)

    mark_not_transfer(conn, TENANT, _id(conn, "t03"))

    assert _flow(conn) == ("5075.00", "3607.05", "1467.95")


def test_a_pending_row_is_not_counted(conn: Connection) -> None:
    doc = json.loads((FIXTURES / "simplefin_transfers.json").read_text(encoding="utf-8"))
    for account in doc["accounts"]:
        for txn in account["transactions"]:
            if txn["id"] == "t02":
                txn["pending"], txn["posted"] = True, 0
    ingest(conn, TENANT, pull_from_text(json.dumps(doc)), UTC_TZ)
    mark_not_transfer(conn, TENANT, _id(conn, "t08"))
    reconcile(conn, TENANT)

    assert _flow(conn)[1] == "757.05"  # 2607.05 minus the 1850.00 rent that is still pending


def _account_id(conn: Connection, external_id: str) -> int:
    row = conn.execute("SELECT id FROM accounts WHERE external_id = %s", (external_id,)).fetchone()
    assert row is not None
    return int(row[0])


@pytest.mark.parametrize("role", ["loan", "investment"])
def test_loan_and_investment_accounts_are_excluded(conn: Connection, role: str) -> None:
    _reconciled(conn)

    set_account_role(conn, TENANT, _account_id(conn, "cc"), role)

    # drops the card's -84.17, -47.88 and +300.00 (its +500.00 was already a transfer)
    assert _flow(conn) == ("3775.00", "2475.00", "1300.00")


def test_the_credit_role_counts_like_on_budget(conn: Connection) -> None:
    _reconciled(conn)

    set_account_role(conn, TENANT, _account_id(conn, "cc"), "credit")

    assert _flow(conn) == ("4075.00", "2607.05", "1467.95")


def test_a_closed_accounts_history_still_counts(conn: Connection) -> None:
    _reconciled(conn)

    conn.execute("UPDATE accounts SET closed = true WHERE external_id = 'sav'")

    assert _flow(conn) == ("4075.00", "2607.05", "1467.95")


def test_the_range_is_inclusive_of_start_and_exclusive_of_end(conn: Connection) -> None:
    _reconciled(conn)

    assert _flow(conn, date(2026, 3, 1), date(2026, 3, 2)) == ("3200.00", "0", "3200.00")
    assert _flow(conn, date(2026, 3, 2), date(2026, 3, 3)) == ("0", "200.00", "-200.00")
    assert _flow(conn, date(2026, 3, 22), date(2026, 3, 23)) == ("300.00", "47.88", "252.12")
    assert _flow(conn, date(2026, 4, 1), date(2026, 5, 1)) == ("0", "0", "0")


def test_other_currencies_and_tenants_see_nothing(conn: Connection) -> None:
    _reconciled(conn)

    other_currency = net_cash_flow(conn, TENANT, *MARCH, "EUR")
    other_tenant = net_cash_flow(conn, "nobody", *MARCH, "USD")

    assert other_currency.totals == {
        "inflow": Decimal("0"),
        "outflow": Decimal("0"),
        "net": Decimal("0"),
    }
    assert other_tenant.value == Decimal("0")


def test_a_refund_counts_as_inflow_in_cash_flow(conn: Connection) -> None:
    account = {
        "id": "a",
        "name": "A",
        "conn_id": "C",
        "currency": "USD",
        "balance": "0",
        "balance-date": 1774958400,
        "transactions": [
            {
                "id": "buy",
                "posted": 1773081000,
                "amount": "-30.00",
                "description": "SHOP",
                "extra": {"category": "groceries"},
            },
            {
                "id": "refund",
                "posted": 1773167400,
                "amount": "20.00",
                "description": "SHOP REFUND",
                "extra": {"category": "groceries"},
            },
        ],
    }
    doc = {"errlist": [], "connections": [{"conn_id": "C", "name": "Bank"}], "accounts": [account]}
    ingest(conn, TENANT, pull_from_text(json.dumps(doc)), UTC_TZ)

    assert _flow(conn) == ("20.00", "30.00", "-10.00")
    assert (
        classify(
            Decimal("20.00"),
            is_internal_transfer=False,
            category="groceries",
            category_is_income=False,
        )
        is Kind.CREDIT
    )


def test_the_sql_agrees_with_the_classifier(conn: Connection) -> None:
    conn.execute(
        "INSERT INTO categories (tenant_id, group_name, name, is_income) "
        "VALUES (%s, 'Work', 'side_gig', true)",
        (TENANT,),
    )
    _reconciled(conn)
    rows: list[tuple[Any, ...]] = conn.execute(
        """
        SELECT t.amount, t.is_internal_transfer, t.category, coalesce(c.is_income, false)
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        LEFT JOIN categories c ON c.tenant_id = t.tenant_id AND c.name = t.category
        WHERE NOT t.pending AND a.role IN ('on_budget', 'credit')
        """
    ).fetchall()

    inflow = outflow = Decimal(0)
    for amount, transfer, category, is_income in rows:
        kind = classify(
            amount, is_internal_transfer=transfer, category=category, category_is_income=is_income
        )
        if kind is Kind.TRANSFER:
            continue
        if amount > 0:
            inflow += amount
        else:
            outflow -= amount

    assert (str(inflow), str(outflow)) == _flow(conn)[:2]
    income_rows = [r for r in rows if r[3]]
    assert [r[2] for r in income_rows] == ["income"]  # the flag, not the name, picks income


def test_net_cash_flow_is_a_scalar_result_not_a_monthly_series(conn: Connection) -> None:
    _reconciled(conn)

    result = net_cash_flow(conn, TENANT, *MARCH, "USD")

    assert type(result) is QueryResult[ScalarRow]
    assert result.rows is None and result.value == Decimal("1467.95")
