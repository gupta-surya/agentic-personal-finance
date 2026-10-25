"""Bronze -> normalize -> silver, end to end against Postgres."""

import hashlib
import json
from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

import psycopg
import pytest
from psycopg.errors import CheckViolation

from finance_agent.db.loader import Connection
from finance_agent.ingest.bronze import record_pull
from finance_agent.ingest.contract import (
    NormalizedAccount,
    NormalizedBatch,
    NormalizedConnection,
    NormalizedTransaction,
    NormalizeResult,
    RawPull,
)
from finance_agent.ingest.pipeline import ingest
from finance_agent.queries.spend import spend_by_category
from tests.helpers import (
    FIXTURES,
    UTC_TZ,
    alembic,
    ingest_file,
    pull_from_file,
    pull_from_text,
)

TENANT = "demo-tenant"
V1 = "simplefin_demo.json"
V2 = "simplefin_v2_demo.json"


def _count(conn: Connection, query: str) -> int:
    row = conn.execute(query).fetchone()
    assert row is not None
    return int(row[0])


def _counts(conn: Connection) -> dict[str, int]:
    return {
        table: _count(conn, f"SELECT count(*) FROM {table}")
        for table in ("raw_pulls", "connections", "accounts", "transactions")
    }


def _v1_body(*accounts: dict[str, object]) -> str:
    return json.dumps({"errors": [], "accounts": list(accounts)})


def _v1_account(
    domain: str, account_id: str = "acct-1", name: str = "Checking"
) -> dict[str, object]:
    return {
        "org": {"domain": domain, "name": domain, "sfin-url": f"https://sfin.{domain}"},
        "id": account_id,
        "name": name,
        "currency": "USD",
        "balance": "10.00",
        "transactions": [
            {"id": "t1", "posted": 1773081000, "amount": "-3.00", "description": name}
        ],
    }


# --- collisions (B1) -------------------------------------------------------


def test_same_account_id_under_two_v2_connections_coexists(conn: Connection) -> None:
    result = ingest_file(conn, TENANT, V2)

    assert (result.status, result.dialect, result.accounts, result.transactions) == (
        "ok",
        "v2",
        2,
        4,
    )
    rows = conn.execute(
        """
        SELECT c.provider_key, a.external_id, a.name, count(t.id)
        FROM accounts a
        JOIN connections c ON c.id = a.connection_id
        LEFT JOIN transactions t ON t.account_id = a.id
        GROUP BY c.provider_key, a.external_id, a.name
        ORDER BY c.provider_key
        """
    ).fetchall()
    assert rows == [
        ("CON-A", "chk-001", "Alex Checking", 2),
        ("CON-B", "chk-001", "Sam Checking", 2),
    ]
    # The same transaction id under both accounts keeps each account's own amount.
    amounts = conn.execute(
        "SELECT c.provider_key, t.amount FROM transactions t "
        "JOIN accounts a ON a.id = t.account_id JOIN connections c ON c.id = a.connection_id "
        "WHERE t.external_id = 'txn-001' ORDER BY c.provider_key"
    ).fetchall()
    assert amounts == [("CON-A", Decimal("-45.10")), ("CON-B", Decimal("-12.00"))]


def test_same_account_id_under_two_v1_orgs_coexists(conn: Connection) -> None:
    body = _v1_body(
        _v1_account("bank-a.example", name="Alpha"), _v1_account("bank-b.example", name="Beta")
    )
    ingest(conn, TENANT, pull_from_text(body), UTC_TZ)

    rows = conn.execute(
        "SELECT c.provider_key, a.name FROM accounts a "
        "JOIN connections c ON c.id = a.connection_id ORDER BY c.provider_key"
    ).fetchall()
    assert rows == [("bank-a.example", "Alpha"), ("bank-b.example", "Beta")]
    assert _count(conn, "SELECT count(*) FROM transactions") == 2


def test_connection_names_are_stored_for_both_dialects(conn: Connection) -> None:
    ingest_file(conn, TENANT, V1)
    ingest_file(conn, TENANT, V2)

    rows = conn.execute("SELECT source, provider_key, name FROM connections ORDER BY 2").fetchall()
    assert rows == [
        ("simplefin", "CON-A", "Demo Bank - Alex"),
        ("simplefin", "CON-B", "Demo Bank - Sam"),
        ("simplefin", "demo-bank.example", "Demo Bank"),
        ("simplefin", "demo-card.example", "Demo Card Co"),
    ]


# --- pending and dates (B2) ------------------------------------------------


def test_pending_transaction_is_stored_without_a_posted_date(conn: Connection) -> None:
    ingest_file(conn, TENANT, V2)

    row = conn.execute(
        "SELECT posted_date, transacted_date, pending, amount FROM transactions "
        "WHERE external_id = 'txn-002'"
    ).fetchone()
    assert row == (None, date(2026, 3, 30), True, Decimal("-6.25"))


def test_posted_transaction_cannot_lose_its_posted_date(conn: Connection) -> None:
    ingest_file(conn, TENANT, V2)

    with pytest.raises(CheckViolation):
        conn.execute("UPDATE transactions SET posted_date = NULL WHERE external_id = 'txn-003'")


@pytest.mark.parametrize(
    ("tz", "march_groceries"),
    [
        (ZoneInfo("UTC"), Decimal("285.32")),
        (ZoneInfo("America/New_York"), Decimal("315.31")),  # cc-txn-009 lands on Mar 31
        (ZoneInfo("Asia/Kolkata"), Decimal("346.72")),  # cc-txn-001 lands on Mar 1
    ],
)
def test_month_totals_depend_on_the_users_timezone(
    conn: Connection, tz: ZoneInfo, march_groceries: Decimal
) -> None:
    ingest(conn, TENANT, pull_from_file(V1), tz)

    assert spend_by_category(conn, TENANT, date(2026, 3, 1), "groceries") == march_groceries


# --- bronze (B6, B7) -------------------------------------------------------


def test_bronze_stores_the_exact_bytes_and_a_matching_hash(conn: Connection) -> None:
    original = (FIXTURES / V1).read_bytes()
    ingest_file(conn, TENANT, V1)

    row = conn.execute(
        "SELECT body, body_sha256, dialect_detected, parse_status, source, fetched_at "
        "FROM raw_pulls"
    ).fetchone()
    assert row is not None
    assert bytes(row[0]) == original
    assert row[1] == hashlib.sha256(original).hexdigest()
    assert (row[2], row[3], row[4]) == ("v1", "ok", "simplefin")
    assert row[5].isoformat() == "2026-04-02T12:00:00+00:00"


def test_reordered_keys_are_a_different_bronze_row_with_original_order_kept(
    conn: Connection,
) -> None:
    original = (FIXTURES / V2).read_bytes()
    doc = json.loads(original)
    reordered = json.dumps(
        {"accounts": doc["accounts"], "connections": doc["connections"], "errlist": doc["errlist"]}
    ).encode()

    first = ingest(conn, TENANT, pull_from_text(original), UTC_TZ)
    second = ingest(conn, TENANT, pull_from_text(reordered), UTC_TZ)

    assert (first.created, second.created) == (True, True)
    assert first.raw_pull_id != second.raw_pull_id
    stored = conn.execute("SELECT body FROM raw_pulls WHERE id = %s", (first.raw_pull_id,))
    row = stored.fetchone()
    assert row is not None
    assert bytes(row[0]).index(b"errlist") < bytes(row[0]).index(b"accounts")


def test_malformed_json_is_kept_in_bronze_and_leaves_silver_untouched(conn: Connection) -> None:
    result = ingest(conn, TENANT, pull_from_text(b"{not json"), UTC_TZ)

    assert (result.status, result.accounts, result.transactions) == ("invalid", 0, 0)
    row = conn.execute("SELECT parse_status, body, body_json FROM raw_pulls").fetchone()
    assert row is not None
    assert (row[0], bytes(row[1]), row[2]) == ("invalid", b"{not json", None)
    assert _counts(conn) == {"raw_pulls": 1, "connections": 0, "accounts": 0, "transactions": 0}


def test_invalid_utf8_bytes_are_stored_exactly(conn: Connection) -> None:
    junk = b"\xff\xfe{\x00 broken"

    result = ingest(conn, TENANT, pull_from_text(junk), UTC_TZ)

    assert result.status == "invalid"
    row = conn.execute("SELECT body FROM raw_pulls").fetchone()
    assert row is not None and bytes(row[0]) == junk


def test_unrecognized_shape_is_kept_in_bronze(conn: Connection) -> None:
    result = ingest(conn, TENANT, pull_from_text(b'{"hello": "world"}'), UTC_TZ)

    assert result.status == "unrecognized"
    row = conn.execute("SELECT parse_status, body_json FROM raw_pulls").fetchone()
    assert row == ("unrecognized", {"hello": "world"})
    assert _counts(conn)["accounts"] == 0


def test_json_that_postgres_rejects_still_keeps_the_bytes(conn: Connection) -> None:
    body = b'{"errors": [], "accounts": [], "note": "bad \\u0000 escape"}'

    result = ingest(conn, TENANT, pull_from_text(body), UTC_TZ)

    assert result.status == "ok"
    row = conn.execute("SELECT body, body_json FROM raw_pulls").fetchone()
    assert row is not None
    assert (bytes(row[0]), row[1]) == (body, None)


def test_unknown_source_is_recorded_but_not_processed(conn: Connection) -> None:
    pull = RawPull(source="mystery", body=b"{}", fetched_at=pull_from_text("x").fetched_at)

    result = ingest(conn, TENANT, pull, UTC_TZ)

    assert result.status == "unrecognized"
    assert "mystery" in (result.message or "")
    assert _counts(conn)["raw_pulls"] == 1


def test_validation_failure_message_is_stored_without_values(conn: Connection) -> None:
    txn = {"id": "t", "posted": 1, "amount": "oops", "description": "SECRET-MERCHANT-9921"}
    account = _v1_account("a.example")
    account["transactions"] = [txn]

    ingest(conn, TENANT, pull_from_text(_v1_body(account)), UTC_TZ)

    row = conn.execute("SELECT parse_status, parse_error FROM raw_pulls").fetchone()
    assert row is not None and row[0] == "invalid"
    assert "SECRET-MERCHANT" not in row[1]


def test_bronze_dedupes_per_tenant_not_globally(conn: Connection) -> None:
    pull = pull_from_file(V1)

    a1 = record_pull(conn, "tenant-a", pull)
    a2 = record_pull(conn, "tenant-a", pull)
    b1 = record_pull(conn, "tenant-b", pull)

    assert a1[1] is True and a2 == (a1[0], False) and b1[1] is True
    assert b1[0] != a1[0]


def test_both_dialect_warning_is_recorded_not_fatal(conn: Connection) -> None:
    account = _v1_account("a.example")
    account["conn_id"] = "CON-X"
    body = json.dumps(
        {
            "errlist": [],
            "connections": [{"conn_id": "CON-X", "name": "X"}],
            "accounts": [account],
        }
    )

    result = ingest(conn, TENANT, pull_from_text(body), UTC_TZ)

    assert (result.status, result.dialect) == ("ok", "v2")
    row = conn.execute("SELECT parse_error FROM raw_pulls").fetchone()
    assert row is not None and "both v1" in row[0]


# --- re-pulls --------------------------------------------------------------


def test_identical_repull_changes_nothing_and_keeps_user_edits(conn: Connection) -> None:
    first = ingest_file(conn, TENANT, V1)
    conn.execute(
        "UPDATE transactions SET category = 'dining', category_source = 'user' "
        "WHERE external_id = 'chk-txn-003'"
    )
    before = _counts(conn)

    second = ingest_file(conn, TENANT, V1)

    assert (first.created, second.created) == (True, False)
    assert first.raw_pull_id == second.raw_pull_id
    assert (
        _counts(conn)
        == before
        == {
            "raw_pulls": 1,
            "connections": 2,
            "accounts": 2,
            "transactions": 12,
        }
    )
    row = conn.execute(
        "SELECT category, category_source FROM transactions WHERE external_id = 'chk-txn-003'"
    ).fetchone()
    assert row == ("dining", "user")


def test_v1_then_v2_then_v1_again(conn: Connection) -> None:
    ingest_file(conn, TENANT, V1)
    ingest_file(conn, TENANT, V2)
    after_both = _counts(conn)
    ingest_file(conn, TENANT, V1)

    assert after_both == {"raw_pulls": 2, "connections": 4, "accounts": 4, "transactions": 16}
    assert _counts(conn) == after_both


def test_unknown_hint_loads_as_uncategorized_in_the_new_pipeline(conn: Connection) -> None:
    account = _v1_account("a.example")
    account["transactions"] = [
        {
            "id": "t1",
            "posted": 1773081000,
            "amount": "-1.00",
            "description": "X",
            "extra": {"category": "invented"},
        }
    ]

    ingest(conn, TENANT, pull_from_text(_v1_body(account)), UTC_TZ)

    row = conn.execute("SELECT category, category_source FROM transactions").fetchone()
    assert row == (None, None)


# --- a second source proves the contract is source-neutral (inverted signs) ---


def _inverted_sign_normalizer(pull: RawPull, tz: ZoneInfo) -> NormalizeResult:
    """A made-up source that reports money OUT as a positive number.

    The sign flip lives here, in the connector's normalize step, and nowhere else.
    """
    doc = json.loads(pull.body, parse_float=Decimal)
    batch = NormalizedBatch(
        source="inverted-test",
        dialect="v1",
        connections=[NormalizedConnection(provider_key="login-1", name="Inverted Bank")],
        accounts=[
            NormalizedAccount(
                connection_key="login-1",
                external_id=row["account"],
                name="Inverted Checking",
                currency="USD",
                currency_kind="iso",
                balance=Decimal("0"),
            )
            for row in doc["rows"][:1]
        ],
        transactions=[
            NormalizedTransaction(
                connection_key="login-1",
                account_external_id=row["account"],
                external_id=row["id"],
                amount=-Decimal(str(row["out"])),  # positive "out" becomes a negative debit
                description=row["memo"],
                posted_date=date.fromisoformat(row["date"]),
                category_hint="groceries",
                raw=json.dumps(row),
            )
            for row in doc["rows"]
        ],
    )
    return NormalizeResult(status="ok", batch=batch, dialect="v1")


def test_inverted_sign_source_stores_the_same_signed_amounts(conn: Connection) -> None:
    simplefin = _v1_body(
        {
            "org": {"domain": "bank.example"},
            "id": "A1",
            "name": "Checking",
            "currency": "USD",
            "balance": "0",
            "transactions": [
                {
                    "id": "x1",
                    "posted": 1773081000,
                    "amount": "-12.50",
                    "description": "MARKET",
                    "extra": {"category": "groceries"},
                }
            ],
        }
    )
    inverted = json.dumps(
        {
            "rows": [
                {
                    "account": "A1",
                    "id": "x1",
                    "out": "12.50",
                    "memo": "MARKET",
                    "date": "2026-03-09",
                }
            ]
        }
    )

    ingest(conn, TENANT, pull_from_text(simplefin), UTC_TZ)
    result = ingest(
        conn,
        TENANT,
        pull_from_text(inverted, source="inverted-test"),
        UTC_TZ,
        normalizers={"inverted-test": _inverted_sign_normalizer},
    )

    assert (result.status, result.transactions) == ("ok", 1)
    rows = conn.execute(
        "SELECT c.source, a.external_id, t.external_id, t.amount "
        "FROM transactions t JOIN accounts a ON a.id = t.account_id "
        "JOIN connections c ON c.id = a.connection_id ORDER BY c.source"
    ).fetchall()
    # Same account id and transaction id in two sources: no collision, same stored amount.
    assert rows == [
        ("inverted-test", "A1", "x1", Decimal("-12.50")),
        ("simplefin", "A1", "x1", Decimal("-12.50")),
    ]
    assert spend_by_category(conn, TENANT, date(2026, 3, 1), "groceries") == Decimal("25.00")


# --- migrations with data and connection hygiene -------------------------


def test_downgrade_with_data_does_not_crash_and_upgrade_restores(conn: Connection) -> None:
    ingest_file(conn, TENANT, V1)
    ingest_file(conn, TENANT, V2)

    alembic("downgrade", "0002")
    legacy = conn.execute(
        "SELECT (SELECT count(*) FROM raw_payloads), (SELECT count(*) FROM accounts), "
        "(SELECT count(*) FROM transactions)"
    ).fetchone()
    # Two same-id accounts collapse to one; the pending row falls back to its transacted date.
    assert legacy == (2, 3, 15)
    pending = conn.execute(
        "SELECT posted_date FROM transactions WHERE external_id = 'txn-002'"
    ).fetchone()
    assert pending == (date(2026, 3, 30),)

    alembic("upgrade", "head")
    assert _counts(conn)["accounts"] == 3


def test_connection_is_left_usable_after_ingest_errors(conn: Connection) -> None:
    with pytest.raises(psycopg.errors.Error):
        conn.execute("SELECT * FROM table_that_does_not_exist")

    result = ingest_file(conn, TENANT, V1)

    assert result.status == "ok"


def test_bronze_and_silver_loaders_import_nothing_source_specific() -> None:
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "src" / "finance_agent" / "ingest"
    for name in ("bronze.py", "silver_loader.py", "contract.py"):
        tree = ast.parse((root / name).read_text(encoding="utf-8"))
        modules = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        modules += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert not [m for m in modules if "simplefin" in m], f"{name} imports a SimpleFIN module"
