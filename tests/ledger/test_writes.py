"""The ledger write API against real Postgres: user decisions stick, atomic bulk edits, rules
that never touch user rows, transfers, accounts, and tenant isolation."""

from contextlib import nullcontext
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from finance_agent.charts.api import create_app
from finance_agent.charts.templates import default_registry
from finance_agent.db.default_categories import seed_default_categories
from finance_agent.db.loader import Connection
from finance_agent.ingest.pipeline import ingest
from finance_agent.ledger.api import ledger_router
from finance_agent.local_guard import SESSION_HEADER, harden
from finance_agent.queries.pg_catalog import PostgresSeriesCatalog
from tests.catalog_conformance.dataset import dataset, simplefin_body, to_postgres
from tests.helpers import UTC_TZ, pull_from_text

TENANT = "demo-tenant"
OTHER = "other-tenant"
TODAY = date(2026, 11, 15)
WIDE = (date(2025, 1, 1), date(2028, 1, 1))


def _app(conn: Connection, tenant: str = TENANT) -> FastAPI:
    session = lambda: nullcontext(conn)  # noqa: E731
    return create_app(
        default_registry(),
        lambda: nullcontext(PostgresSeriesCatalog(conn, tenant)),
        lambda: TODAY,
        source="postgres",
        ledger=ledger_router(session, tenant, lambda: TODAY, session),
    )


def _client(conn: Connection, tenant: str = TENANT) -> TestClient:
    return TestClient(_app(conn, tenant))


@pytest.fixture
def seeded(conn: Connection) -> Connection:
    to_postgres(conn, TENANT, dataset())
    return conn


def _txn(conn: Connection, description: str, tenant: str = TENANT) -> int:
    row = conn.execute(
        "SELECT id FROM transactions WHERE tenant_id = %s AND description = %s",
        (tenant, description),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _state(conn: Connection, txn_id: int) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT category, category_source, note, hidden FROM transactions WHERE id = %s", (txn_id,)
    ).fetchone()
    assert row is not None
    return tuple(row)


def _spend(conn: Connection) -> Decimal:
    return PostgresSeriesCatalog(conn, TENANT).kpi("spend", *WIDE, "USD").value  # type: ignore[return-value]


def _acme(conn: Connection) -> tuple[int, int]:
    """Two rows of one merchant; the dataset's descriptions carry no merchant, so name them."""
    conn.execute(
        "UPDATE transactions SET description = %s, merchant_normalized = NULL "
        "WHERE tenant_id = %s AND description = ANY(%s)",
        ("ACME STORE 1", TENANT, ["TXN 2"]),
    )
    conn.execute(
        "UPDATE transactions SET description = %s, merchant_normalized = NULL "
        "WHERE tenant_id = %s AND description = ANY(%s)",
        ("ACME STORE 2", TENANT, ["TXN 3"]),
    )
    return _txn(conn, "ACME STORE 1"), _txn(conn, "ACME STORE 2")


def test_patch_category_is_a_user_decision_with_a_user_rule(seeded: Connection) -> None:
    first, second = _acme(seeded)
    response = _client(seeded).patch(f"/api/transactions/{first}", json={"category": "travel"})
    assert response.status_code == 200, response.text
    body = response.json()["transaction"]
    assert (body["category"], body["category_source"]) == ("travel", "user")
    rule = seeded.execute(
        "SELECT category, source FROM merchant_rules WHERE tenant_id = %s "
        "AND merchant_normalized = 'ACME'",
        (TENANT,),
    ).fetchone()
    assert rule == ("travel", "user")  # invariant 6: a correction is a rule
    assert _state(seeded, second)[:2] == ("travel", "rule")  # the merchant's other row follows


def test_a_user_category_and_hidden_row_survive_a_resync(seeded: Connection) -> None:
    row = _txn(seeded, "TXN 5")
    client = _client(seeded)
    assert (
        client.patch(
            f"/api/transactions/{row}", json={"category": "travel", "hidden": True, "note": "n"}
        ).status_code
        == 200
    )
    rows = dataset()
    from finance_agent.charts.fake_catalog import SyntheticTransaction
    from tests.catalog_conformance.dataset import Row

    extra = Row(SyntheticTransaction(date(2026, 11, 1), Decimal("-1.00"), "dining"), "checking")
    assert (
        ingest(seeded, TENANT, pull_from_text(simplefin_body([*rows, extra])), UTC_TZ).status
        == "ok"
    )
    assert _state(seeded, row) == ("travel", "user", "n", True)


def test_patch_validation_and_errors(seeded: Connection) -> None:
    client = _client(seeded)
    row = _txn(seeded, "TXN 5")
    assert client.patch(f"/api/transactions/{row}", json={}).status_code == 422
    assert client.patch(f"/api/transactions/{row}", json={"category": "nope"}).status_code == 422
    assert client.patch(f"/api/transactions/{row}", json={"bogus": 1}).status_code == 422
    assert client.patch("/api/transactions/999999", json={"hidden": True}).status_code == 404
    leg = seeded.execute(
        "SELECT id FROM transactions WHERE tenant_id = %s AND is_internal_transfer LIMIT 1",
        (TENANT,),
    ).fetchone()
    assert leg is not None  # a transfer leg has no category
    assert (
        client.patch(f"/api/transactions/{leg[0]}", json={"category": "dining"}).status_code == 422
    )
    assert client.post(f"/api/transactions/{row}/accept-suggestion").status_code == 409
    # a note can be cleared
    client.patch(f"/api/transactions/{row}", json={"note": "x"})
    client.patch(f"/api/transactions/{row}", json={"note": None})
    assert _state(seeded, row)[2] is None


def test_hiding_removes_a_row_from_totals_and_unhiding_restores_it(seeded: Connection) -> None:
    row = _txn(seeded, "TXN 5")
    amount = seeded.execute("SELECT amount FROM transactions WHERE id = %s", (row,)).fetchone()
    assert amount is not None and amount[0] < 0
    before = _spend(seeded)
    version = PostgresSeriesCatalog(seeded, TENANT).kpi("spend", *WIDE, "USD").data_version
    client = _client(seeded)
    client.patch(f"/api/transactions/{row}", json={"hidden": True})
    assert _spend(seeded) == before + amount[0]  # spend is -SUM(amount): the row leaves it
    hidden_version = PostgresSeriesCatalog(seeded, TENANT).kpi("spend", *WIDE, "USD").data_version
    assert hidden_version != version
    client.patch(f"/api/transactions/{row}", json={"hidden": False})
    assert _spend(seeded) == before


def test_bulk_is_all_or_nothing_and_capped(seeded: Connection) -> None:
    a, b = _txn(seeded, "TXN 5"), _txn(seeded, "TXN 6")
    client = _client(seeded)
    ok = client.post("/api/transactions/bulk", json={"ids": [a, b, a], "category": "travel"})
    assert ok.json() == {"updated": 2}
    assert _state(seeded, a)[:2] == _state(seeded, b)[:2] == ("travel", "user")
    c = _txn(seeded, "TXN 7")
    before = _state(seeded, c)
    bad = client.post("/api/transactions/bulk", json={"ids": [c, 999999], "hidden": True})
    assert bad.status_code == 404 and _state(seeded, c) == before  # nothing was changed
    assert client.post("/api/transactions/bulk", json={"ids": list(range(501))}).status_code == 422
    assert client.post("/api/transactions/bulk", json={"ids": []}).status_code == 422
    unknown = client.post("/api/transactions/bulk", json={"ids": [c], "category": "nope"})
    assert unknown.status_code == 422 and _state(seeded, c) == before


def test_rules_never_touch_user_rows_and_preview_writes_nothing(seeded: Connection) -> None:
    first, second = _acme(seeded)
    client = _client(seeded)
    client.patch(f"/api/transactions/{first}", json={"category": "dining"})  # a user row
    body = {"merchant": "ACME", "category": "travel", "apply_to_existing": True}
    rules_before = seeded.execute("SELECT count(*) FROM merchant_rules").fetchone()
    preview = client.post("/api/rules?preview=1", json=body)
    assert preview.json() == {"count": 1, "preview": True}
    assert _state(seeded, second)[:2] != ("travel", "rule")
    assert seeded.execute("SELECT count(*) FROM merchant_rules").fetchone() == rules_before

    applied = client.post("/api/rules", json=body)
    assert applied.json() == {"count": 1, "preview": False}
    assert _state(seeded, first)[:2] == ("dining", "user")  # the user's row is untouched
    assert _state(seeded, second)[:2] == ("travel", "rule")


def test_a_rule_without_apply_leaves_existing_rows(seeded: Connection) -> None:
    _, second = _acme(seeded)
    body = {"merchant": "ACME", "category": "travel", "apply_to_existing": False}
    assert _client(seeded).post("/api/rules", json=body).json() == {"count": 0, "preview": False}
    assert _state(seeded, second)[:2] != ("travel", "rule")
    bad = {"merchant": "!!!", "category": "travel"}
    assert _client(seeded).post("/api/rules", json=bad).status_code == 422


def test_transfer_actions(seeded: Connection) -> None:
    client = _client(seeded)
    leg = seeded.execute(
        "SELECT id FROM transactions WHERE tenant_id = %s AND is_internal_transfer "
        "ORDER BY id LIMIT 1",
        (TENANT,),
    ).fetchone()
    assert leg is not None
    body = client.post(f"/api/transactions/{leg[0]}/transfer", json={"action": "not_transfer"})
    assert body.status_code == 200 and body.json()["transaction"]["transfer"] is None
    left = seeded.execute(
        "SELECT count(*) FROM transactions WHERE tenant_id = %s AND is_internal_transfer", (TENANT,)
    ).fetchone()
    assert left == (2,)  # that group's two legs are no longer transfers

    # link the two freed legs back together: opposite amounts in different accounts
    legs = [
        r[0]
        for r in seeded.execute(
            "SELECT id FROM transactions WHERE tenant_id = %s AND transfer_source = 'user' "
            "ORDER BY id",
            (TENANT,),
        ).fetchall()
    ]
    assert len(legs) == 2
    linked = client.post(
        f"/api/transactions/{legs[0]}/transfer", json={"action": "link", "other_id": legs[1]}
    )
    assert linked.status_code == 200 and linked.json()["transaction"]["transfer"]["group_id"]
    assert linked.json()["transaction"]["transfer"]["confidence"] == "high"
    a, b = _txn(seeded, "TXN 5"), _txn(seeded, "TXN 6")
    refused = client.post(f"/api/transactions/{a}/transfer", json={"action": "link", "other_id": b})
    assert refused.status_code == 422
    assert (
        client.post(f"/api/transactions/{a}/transfer", json={"action": "link"}).status_code == 422
    )
    assert (
        client.post(
            "/api/transactions/999999/transfer", json={"action": "not_transfer"}
        ).status_code
        == 404
    )


def test_patch_account(seeded: Connection) -> None:
    client = _client(seeded)
    account = seeded.execute(
        "SELECT id FROM accounts WHERE tenant_id = %s AND name = 'euro'", (TENANT,)
    ).fetchone()
    assert account is not None
    response = client.patch(
        f"/api/accounts/{account[0]}", json={"role": "investment", "display_name": " Brokerage "}
    )
    assert response.status_code == 200, response.text
    row = seeded.execute(
        "SELECT role, role_source, display_name FROM accounts WHERE id = %s", (account[0],)
    ).fetchone()
    assert row == ("investment", "user", "Brokerage")
    client.patch(f"/api/accounts/{account[0]}", json={"display_name": None, "hidden": True})
    row = seeded.execute(
        "SELECT display_name, hidden FROM accounts WHERE id = %s", (account[0],)
    ).fetchone()
    assert row == (None, True)
    assert client.patch(f"/api/accounts/{account[0]}", json={"role": "bank"}).status_code == 422
    assert client.patch(f"/api/accounts/{account[0]}", json={}).status_code == 422
    assert client.patch("/api/accounts/999999", json={"hidden": True}).status_code == 404


def test_another_tenant_is_untouchable_on_write(seeded: Connection) -> None:
    seed_default_categories(seeded, OTHER)
    to_postgres(seeded, OTHER, dataset())
    theirs = _txn(seeded, "TXN 5", OTHER)
    their_account = seeded.execute(
        "SELECT id FROM accounts WHERE tenant_id = %s LIMIT 1", (OTHER,)
    ).fetchone()
    assert their_account is not None
    before = _state(seeded, theirs)
    client = _client(seeded, TENANT)
    assert client.patch(f"/api/transactions/{theirs}", json={"hidden": True}).status_code == 404
    mine = _txn(seeded, "TXN 6")
    mixed = client.post("/api/transactions/bulk", json={"ids": [mine, theirs], "hidden": True})
    assert mixed.status_code == 404
    assert (
        client.post(
            f"/api/transactions/{theirs}/transfer", json={"action": "not_transfer"}
        ).status_code
        == 404
    )
    assert (
        client.patch(f"/api/accounts/{their_account[0]}", json={"hidden": True}).status_code == 404
    )
    assert _state(seeded, theirs) == before and _state(seeded, mine)[3] is False
    # a rule only ever lands in the caller's own tenant
    client.post("/api/rules", json={"merchant": "zzz shop", "category": "travel"})
    leaked = seeded.execute(
        "SELECT count(*) FROM merchant_rules "
        "WHERE tenant_id = %s AND merchant_normalized = 'ZZZ SHOP'",
        (OTHER,),
    ).fetchone()
    assert leaked == (0,)


def test_writes_need_the_session_token_when_hardened(seeded: Connection) -> None:
    app = harden(_app(seeded), 8123)
    client = TestClient(app, base_url="http://127.0.0.1:8123")
    row = _txn(seeded, "TXN 5")
    assert client.patch(f"/api/transactions/{row}", json={"hidden": True}).status_code == 401
    cross = {SESSION_HEADER: app.state.session_token, "Origin": "http://evil.example"}
    assert (
        client.patch(f"/api/transactions/{row}", json={"hidden": True}, headers=cross).status_code
        == 403
    )
    assert _state(seeded, row)[3] is False
    ok = {SESSION_HEADER: app.state.session_token}
    assert (
        client.patch(f"/api/transactions/{row}", json={"hidden": True}, headers=ok).status_code
        == 200
    )
