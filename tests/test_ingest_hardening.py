"""TASK-02b: connector errors, balance freshness, pending tracking, currency, efficiency."""

import json
import socket
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg.rows import TupleRow

from finance_agent.db.default_categories import seed_default_categories
from finance_agent.db.loader import Connection
from finance_agent.ingest.contract import RawPull
from finance_agent.ingest.pipeline import IngestResult, ingest
from finance_agent.ingest.sanitize import sanitize_for_display
from finance_agent.queries.spend import spend_by_category
from tests.helpers import (
    UTC_TZ,
    database_url,
    ingest_file,
    pull_from_file,
    pull_from_text,
)

TENANT = "demo-tenant"
T1 = datetime(2026, 4, 2, 12, 0, tzinfo=UTC)
T2 = T1 + timedelta(hours=1)
T3 = T1 + timedelta(hours=2)
PENDING = {"version": "2", "pending": "1"}
MARCH = date(2026, 3, 1)


# --- body builders ---------------------------------------------------------


def _txn(
    txn_id: str,
    amount: str = "-5.00",
    posted: int = 1773081000,
    pending: bool = False,
    transacted_at: int | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    txn: dict[str, Any] = {
        "id": txn_id,
        "posted": 0 if pending else posted,
        "amount": amount,
        "description": f"merchant {txn_id}",
    }
    if pending:
        txn["pending"] = True
    if transacted_at is not None:
        txn["transacted_at"] = transacted_at
    if category is not None:
        txn["extra"] = {"category": category}
    return txn


def _account(
    txns: list[dict[str, Any]],
    conn_id: str = "CON-A",
    account_id: str = "acct",
    name: str = "Checking",
    balance: str = "100.00",
    balance_date: int = 1774958400,
    currency: str = "USD",
) -> dict[str, Any]:
    return {
        "id": account_id,
        "name": name,
        "conn_id": conn_id,
        "currency": currency,
        "balance": balance,
        "balance-date": balance_date,
        "transactions": txns,
    }


def _v2(
    accounts: list[dict[str, Any]],
    errlist: list[dict[str, str]] | None = None,
    connections: tuple[str, ...] = ("CON-A",),
) -> str:
    return json.dumps(
        {
            "errlist": errlist or [],
            "connections": [{"conn_id": c, "name": f"Bank {c}"} for c in connections],
            "accounts": accounts,
        }
    )


def _pull(body: str, fetched_at: datetime = T1, params: dict[str, str] | None = None) -> RawPull:
    return RawPull(
        source="simplefin",
        body=body.encode(),
        fetched_at=fetched_at,
        request_params=params or {},
    )


def _go(
    conn: Connection,
    body: str,
    fetched_at: datetime = T1,
    params: dict[str, str] | None = None,
    tenant: str = TENANT,
) -> IngestResult:
    return ingest(conn, tenant, _pull(body, fetched_at, params), UTC_TZ)


def _one(conn: Connection, query: str, *params: object) -> tuple[Any, ...]:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return tuple(row)


def _stale(conn: Connection) -> dict[tuple[str, str], bool]:
    rows = conn.execute(
        "SELECT c.provider_key, a.external_id, a.stale FROM accounts a "
        "JOIN connections c ON c.id = a.connection_id"
    ).fetchall()
    return {(r[0], r[1]): r[2] for r in rows}


# --- B3: connector errors --------------------------------------------------


def test_v2_errlist_is_persisted_with_its_scope_and_marks_the_connection_stale(
    conn: Connection,
) -> None:
    ingest_file(conn, TENANT, "simplefin_v2_demo.json")

    errors = conn.execute(
        "SELECT e.code, e.message, c.provider_key, e.account_id FROM pull_errors e "
        "LEFT JOIN connections c ON c.id = e.connection_id"
    ).fetchall()
    assert errors == [("con.auth", "Authentication required for Demo Bank - Sam", "CON-B", None)]
    assert _stale(conn) == {("CON-A", "chk-001"): False, ("CON-B", "chk-001"): True}


def test_v1_errors_are_persisted_as_legacy_without_scope(conn: Connection) -> None:
    account = {
        "org": {"domain": "a.example"},
        "id": "1",
        "name": "A",
        "currency": "USD",
        "balance": "1",
    }
    body = json.dumps({"errors": ["You must reauthenticate."], "accounts": [account]})

    ingest(conn, TENANT, pull_from_text(body), UTC_TZ)

    assert conn.execute(
        "SELECT code, message, connection_id, account_id FROM pull_errors"
    ).fetchall() == [("legacy", "You must reauthenticate.", None, None)]
    assert list(_stale(conn).values()) == [False]


def test_account_error_with_a_connection_marks_only_that_account(conn: Connection) -> None:
    accounts = [_account([], conn_id="CON-A"), _account([], conn_id="CON-B")]
    error = {
        "code": "act.missingdata",
        "msg": "Incomplete",
        "account_id": "acct",
        "conn_id": "CON-A",
    }

    _go(conn, _v2(accounts, [error], ("CON-A", "CON-B")))

    assert _stale(conn) == {("CON-A", "acct"): True, ("CON-B", "acct"): False}
    assert _one(conn, "SELECT count(*) FROM pull_errors")[0] == 1


def test_account_error_without_a_connection_covers_every_account_with_that_id(
    conn: Connection,
) -> None:
    accounts = [_account([], conn_id="CON-A"), _account([], conn_id="CON-B")]
    error = {"code": "act.failed", "msg": "Try later", "account_id": "acct"}

    _go(conn, _v2(accounts, [error], ("CON-A", "CON-B")))

    assert _stale(conn) == {("CON-A", "acct"): True, ("CON-B", "acct"): True}
    assert _one(conn, "SELECT count(*) FROM pull_errors")[0] == 2  # one row per candidate


def test_a_clean_later_pull_clears_stale(conn: Connection) -> None:
    accounts = [_account([], conn_id="CON-A"), _account([], conn_id="CON-B")]
    error = {"code": "con.auth", "msg": "Reauth", "conn_id": "CON-B"}
    _go(conn, _v2(accounts, [error], ("CON-A", "CON-B")), T1)
    assert _stale(conn)[("CON-B", "acct")] is True

    _go(conn, _v2(accounts, [], ("CON-A", "CON-B")), T2)

    assert _stale(conn) == {("CON-A", "acct"): False, ("CON-B", "acct"): False}


def test_a_failing_connection_returns_no_accounts_but_its_old_accounts_go_stale(
    conn: Connection,
) -> None:
    both = [_account([], conn_id="CON-A"), _account([], conn_id="CON-B")]
    _go(conn, _v2(both, None, ("CON-A", "CON-B")), T1)

    only_a = [_account([], conn_id="CON-A")]
    error = {"code": "con.auth", "msg": "Reauth", "conn_id": "CON-B"}
    _go(conn, _v2(only_a, [error], ("CON-A", "CON-B")), T2)

    assert _stale(conn) == {("CON-A", "acct"): False, ("CON-B", "acct"): True}


def test_the_same_error_is_not_stored_twice_on_an_identical_repull(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_v2_demo.json")
    ingest_file(conn, TENANT, "simplefin_v2_demo.json")

    assert _one(conn, "SELECT count(*) FROM pull_errors")[0] == 1


def test_sanitize_for_display_escapes_strips_and_truncates() -> None:
    assert sanitize_for_display("<script>alert('x')</script>") == (
        "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;"
    )
    assert sanitize_for_display("line1\nline2\ttab\x00nul‮rtl") == "line1line2tabnulrtl"
    long = sanitize_for_display("a" * 500)
    assert len(long) == 200 and long.endswith("…")


def test_the_stored_error_message_is_untouched(conn: Connection) -> None:
    raw = "<b>Reauth</b>\nneeded"
    error = {"code": "con.auth", "msg": raw, "conn_id": "CON-A"}

    _go(conn, _v2([_account([])], [error]))

    assert _one(conn, "SELECT message FROM pull_errors")[0] == raw


# --- B5: balances only move forward ---------------------------------------


def test_an_older_pull_cannot_regress_the_balance_but_still_refreshes_the_name(
    conn: Connection,
) -> None:
    newer = _account([], balance="100.00", balance_date=1774958400, name="Checking")
    older = _account([], balance="50.00", balance_date=1774872000, name="Renamed")
    _go(conn, _v2([newer]), T2)

    _go(conn, _v2([older]), T1)

    row = _one(conn, "SELECT balance, balance_as_of, name FROM accounts")
    assert row == (Decimal("100.00"), datetime(2026, 3, 31, 12, 0, tzinfo=UTC), "Renamed")


def test_equal_and_newer_timestamps_apply(conn: Connection) -> None:
    _go(conn, _v2([_account([], balance="100.00", balance_date=1774958400)]), T1)
    _go(conn, _v2([_account([], balance="101.00", balance_date=1774958400)]), T2)
    assert _one(conn, "SELECT balance FROM accounts")[0] == Decimal("101.00")

    _go(conn, _v2([_account([], balance="102.00", balance_date=1774958500)]), T3)

    assert _one(conn, "SELECT balance, balance_as_of FROM accounts") == (
        Decimal("102.00"),
        datetime(2026, 3, 31, 12, 1, 40, tzinfo=UTC),
    )


def test_available_balance_is_stored_with_the_balance(conn: Connection) -> None:
    ingest_file(conn, TENANT, "simplefin_v2_demo.json")

    rows = conn.execute(
        "SELECT c.provider_key, a.balance, a.available_balance FROM accounts a "
        "JOIN connections c ON c.id = a.connection_id ORDER BY 1"
    ).fetchall()
    assert rows == [
        ("CON-A", Decimal("1500.00"), Decimal("1400.00")),
        ("CON-B", Decimal("250.00"), None),
    ]


# --- B8: pending rows that vanish -----------------------------------------


P_TIME = 1774900000  # 2026-03-30 in UTC


def _pending_first_pull(conn: Connection, transacted_at: int | None = P_TIME) -> None:
    txns = [
        _txn("p1", "-6.25", pending=True, transacted_at=transacted_at),
        _txn("s1", "-1.00", posted=1773081000),
    ]
    _go(conn, _v2([_account(txns)]), T1, PENDING)


def _missing(conn: Connection) -> dict[str, datetime | None]:
    rows = conn.execute("SELECT external_id, missing_since FROM transactions").fetchall()
    return dict(rows)


def test_a_vanished_pending_row_is_flagged_and_unflagged_when_it_returns(
    conn: Connection,
) -> None:
    _pending_first_pull(conn)
    assert _missing(conn) == {"p1": None, "s1": None}

    _go(conn, _v2([_account([_txn("s1", "-1.00"), _txn("s2", "-2.00")])]), T2, PENDING)
    assert _missing(conn) == {"p1": T2, "s1": None, "s2": None}

    back = [_txn("p1", "-6.25", pending=True, transacted_at=P_TIME), _txn("s1", "-1.00")]
    _go(conn, _v2([_account(back)]), T3, PENDING)
    assert _missing(conn) == {"p1": None, "s1": None, "s2": None}


def test_a_posted_row_that_disappears_is_never_flagged(conn: Connection) -> None:
    _pending_first_pull(conn)

    _go(
        conn,
        _v2([_account([_txn("p1", "-6.25", pending=True, transacted_at=P_TIME)])]),
        T2,
        PENDING,
    )

    assert _missing(conn) == {"p1": None, "s1": None}


def test_nothing_is_flagged_if_the_pull_did_not_ask_for_pending(conn: Connection) -> None:
    _pending_first_pull(conn)

    _go(conn, _v2([_account([_txn("s1", "-1.00")])]), T2, {"version": "2"})

    assert _missing(conn)["p1"] is None


def test_nothing_is_flagged_if_an_error_covers_the_account(conn: Connection) -> None:
    _pending_first_pull(conn)
    error = {
        "code": "act.missingdata",
        "msg": "Incomplete",
        "account_id": "acct",
        "conn_id": "CON-A",
    }

    _go(conn, _v2([_account([_txn("s1", "-1.00")])], [error]), T2, PENDING)

    assert _missing(conn)["p1"] is None


def test_a_connection_level_error_also_prevents_flagging(conn: Connection) -> None:
    _pending_first_pull(conn)
    error = {"code": "con.auth", "msg": "Reauth", "conn_id": "CON-A"}

    _go(conn, _v2([_account([_txn("s1", "-1.00")])], [error]), T2, PENDING)

    assert _missing(conn)["p1"] is None


def _window(start: int | None = None, end: int | None = None) -> dict[str, str]:
    params = dict(PENDING)
    if start is not None:
        params["start-date"] = str(start)
    if end is not None:
        params["end-date"] = str(end)
    return params


MARCH_29 = int(datetime(2026, 3, 29, tzinfo=UTC).timestamp())
APRIL_1 = int(datetime(2026, 4, 1, tzinfo=UTC).timestamp())


def test_windowed_pull_flags_a_pending_row_inside_the_window(conn: Connection) -> None:
    _pending_first_pull(conn)  # p1 transacted 2026-03-30

    _go(conn, _v2([_account([_txn("s1", "-1.00")])]), T2, _window(MARCH_29, APRIL_1))

    assert _missing(conn)["p1"] == T2


def test_windowed_pull_leaves_a_pending_row_outside_the_window(conn: Connection) -> None:
    _pending_first_pull(conn)  # p1 transacted 2026-03-30; window starts 2026-04-01

    _go(conn, _v2([_account([_txn("s1", "-1.00")])]), T2, _window(APRIL_1, None))

    assert _missing(conn)["p1"] is None


def test_windowed_pull_never_flags_a_pending_row_without_a_transacted_date(
    conn: Connection,
) -> None:
    _pending_first_pull(conn, transacted_at=None)

    _go(conn, _v2([_account([_txn("s1", "-1.00")])]), T2, _window(MARCH_29, APRIL_1))

    assert _missing(conn)["p1"] is None


def test_unwindowed_pull_flags_a_pending_row_without_a_transacted_date(conn: Connection) -> None:
    _pending_first_pull(conn, transacted_at=None)

    _go(conn, _v2([_account([_txn("s1", "-1.00")])]), T2, PENDING)

    assert _missing(conn)["p1"] == T2


def test_a_boundary_date_row_is_left_alone(conn: Connection) -> None:
    # p1 was transacted on 2026-03-30; a window starting that same day might exclude it.
    _pending_first_pull(conn)
    start = int(datetime(2026, 3, 30, 12, tzinfo=UTC).timestamp())

    _go(conn, _v2([_account([_txn("s1", "-1.00")])]), T2, _window(start))

    assert _missing(conn)["p1"] is None


# --- B9: currency ----------------------------------------------------------


def test_custom_currency_is_stored_flagged_and_excluded_without_any_network(
    conn: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    miles = "https://airline.example/miles"
    accounts = [
        _account([_txn("m1", "-99.00", category="groceries")], account_id="miles", currency=miles),
        _account([_txn("u1", "-10.00", category="groceries")], account_id="usd"),
    ]

    _go(conn, _v2(accounts))

    kinds = conn.execute("SELECT external_id, currency, currency_kind FROM accounts ORDER BY 1")
    assert kinds.fetchall() == [("miles", miles, "custom"), ("usd", "USD", "iso")]
    assert spend_by_category(conn, TENANT, MARCH, "groceries", "USD") == Decimal("10.00")
    assert spend_by_category(conn, TENANT, MARCH, "groceries", miles) == Decimal("0")


def test_spend_for_one_currency_ignores_other_currencies(conn: Connection) -> None:
    accounts = [
        _account([_txn("u1", "-10.00", category="groceries")], account_id="usd"),
        _account([_txn("e1", "-7.00", category="groceries")], account_id="eur", currency="EUR"),
    ]

    _go(conn, _v2(accounts))

    assert spend_by_category(conn, TENANT, MARCH, "groceries", "USD") == Decimal("10.00")
    assert spend_by_category(conn, TENANT, MARCH, "groceries", "EUR") == Decimal("7.00")
    assert spend_by_category(conn, TENANT, MARCH, "groceries", "GBP") == Decimal("0")


# --- B10: efficiency -------------------------------------------------------


def _pairs(conn: Connection, query: str) -> dict[str, Any]:
    """Two-column query -> dict."""
    return {row[0]: row[1] for row in conn.execute(query).fetchall()}


def _versions(conn: Connection) -> dict[str, list[tuple[Any, ...]]]:
    return {
        table: [
            tuple(r)
            for r in conn.execute(f"SELECT id, xmin::text FROM {table} ORDER BY id").fetchall()
        ]
        for table in ("raw_pulls", "connections", "accounts", "transactions", "pull_errors")
    }


@pytest.mark.parametrize("name", ["simplefin_demo.json", "simplefin_v2_demo.json"])
def test_an_identical_repull_writes_zero_rows(conn: Connection, name: str) -> None:
    ingest_file(conn, TENANT, name)
    before = _versions(conn)

    again = ingest_file(conn, TENANT, name)

    assert again.created is False
    assert _versions(conn) == before  # no new row versions anywhere, bronze included


def test_a_real_change_writes_exactly_the_changed_row(conn: Connection) -> None:
    txns = [_txn("t1", "-1.00"), _txn("t2", "-2.00"), _txn("t3", "-3.00")]
    _go(conn, _v2([_account(txns)]), T1)
    before = _pairs(conn, "SELECT external_id, xmin::text FROM transactions")

    changed = [_txn("t1", "-1.00"), _txn("t2", "-2.50"), _txn("t3", "-3.00")]
    _go(conn, _v2([_account(changed)]), T2)

    after = _pairs(conn, "SELECT external_id, xmin::text FROM transactions")
    assert {k for k in before if before[k] != after[k]} == {"t2"}
    stamps = _pairs(conn, "SELECT external_id, last_changed_at FROM transactions")
    assert stamps == {"t1": T1, "t2": T2, "t3": T1}
    assert _one(conn, "SELECT amount FROM transactions WHERE external_id = 't2'")[0] == Decimal(
        "-2.50"
    )


class _CountingCursor(psycopg.Cursor[TupleRow]):
    calls = 0

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        _CountingCursor.calls += 1
        return super().execute(*args, **kwargs)

    def executemany(self, *args: Any, **kwargs: Any) -> None:
        _CountingCursor.calls += 1
        super().executemany(*args, **kwargs)


def _statements_for(counting: Connection, rows: int, account_id: str) -> int:
    txns = [_txn(f"t{i}", "-1.00", category="groceries") for i in range(rows)]
    body = _v2([_account(txns, account_id=account_id)])
    _CountingCursor.calls = 0
    ingest(counting, TENANT, _pull(body, T1), UTC_TZ)
    return _CountingCursor.calls


def test_statements_per_pull_do_not_grow_with_row_count(conn: Connection) -> None:
    with psycopg.connect(
        database_url(), autocommit=True, cursor_factory=_CountingCursor
    ) as counting:
        small = _statements_for(counting, 12, "small")
        large = _statements_for(counting, 120, "large")

    assert small == large
    assert small < 40
    assert _one(conn, "SELECT count(*) FROM transactions")[0] == 132


def test_the_body_json_is_parsed_once_per_ingest(
    conn: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = json.loads
    calls: list[int] = []

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(json, "loads", counting)

    result = ingest(conn, TENANT, pull_from_file("simplefin_demo.json"), UTC_TZ)

    assert result.status == "ok"
    assert len(calls) == 1


def test_other_tenants_are_untouched_by_a_pull(conn: Connection) -> None:
    seed_default_categories(conn, "other-tenant")
    _go(conn, _v2([_account([_txn("t1", category="groceries")])]), T1, tenant="other-tenant")
    before = _versions(conn)

    _go(conn, _v2([_account([_txn("t1", category="groceries")], balance="1.00")]), T2)

    other = conn.execute("SELECT count(*) FROM accounts WHERE tenant_id = 'other-tenant'")
    assert other.fetchone() == (1,)
    assert [v for v in _versions(conn)["accounts"] if v in before["accounts"]] == before["accounts"]
