"""SimpleFIN dialect detection and normalization. Pure code: no database."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from finance_agent.clients.simplefin import FixtureSimpleFinClient, LiveSimpleFinClient
from finance_agent.ingest.contract import NormalizedBatch, NormalizedTransaction, PullError
from finance_agent.ingest.simplefin.common import local_date
from finance_agent.ingest.simplefin.detect import detect_dialect
from finance_agent.ingest.simplefin.normalize import normalize_simplefin
from finance_agent.ingest.simplefin.request import simplefin_request_params
from tests.helpers import FETCHED_AT, FIXTURES, UTC_TZ, pull_from_file, pull_from_text

NEW_YORK = ZoneInfo("America/New_York")
KOLKATA = ZoneInfo("Asia/Kolkata")


def _doc(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _normalize(name: str, tz: ZoneInfo = UTC_TZ) -> NormalizedBatch:
    result = normalize_simplefin(pull_from_file(name), tz)
    assert result.status == "ok", result.message
    assert result.batch is not None
    return result.batch


def _txn(
    batch: NormalizedBatch, external_id: str, connection: str | None = None
) -> NormalizedTransaction:
    matches = [
        t
        for t in batch.transactions
        if t.external_id == external_id and connection in (None, t.connection_key)
    ]
    assert len(matches) == 1
    return matches[0]


# --- detection -------------------------------------------------------------


def test_detects_v1_and_v2_fixtures() -> None:
    assert detect_dialect(_doc("simplefin_demo.json")).dialect == "v1"
    assert detect_dialect(_doc("simplefin_v2_demo.json")).dialect == "v2"


def test_empty_v1_account_set_is_still_v1() -> None:
    assert detect_dialect({"errors": [], "accounts": []}).dialect == "v1"


def test_both_shapes_is_v2_with_a_warning() -> None:
    doc = {"errlist": [], "accounts": [{"org": {"domain": "x"}, "conn_id": "C"}]}

    detection = detect_dialect(doc)

    assert detection.dialect == "v2"
    assert len(detection.warnings) == 1


@pytest.mark.parametrize(
    "doc", [{"hello": 1}, [], "text", {"accounts": "no"}, {"accounts": []}, None]
)
def test_neither_shape_is_unrecognized(doc: object) -> None:
    assert detect_dialect(doc).dialect == "unrecognized"


# --- v1 --------------------------------------------------------------------


def test_v1_fixture_normalizes() -> None:
    batch = _normalize("simplefin_demo.json")

    assert (batch.source, batch.dialect) == ("simplefin", "v1")
    assert [(c.provider_key, c.name) for c in batch.connections] == [
        ("demo-bank.example", "Demo Bank"),
        ("demo-card.example", "Demo Card Co"),
    ]
    assert len(batch.accounts) == 2
    assert len(batch.transactions) == 12
    assert batch.errors == []

    grocery = _txn(batch, "chk-txn-003")
    assert grocery.amount == Decimal("-12.49")
    assert grocery.posted_date == date(2026, 3, 9)
    assert grocery.category_hint == "groceries"
    assert grocery.connection_key == "demo-bank.example"
    assert not grocery.pending


def test_v1_errors_become_legacy_pull_errors() -> None:
    body = json.dumps({"errors": ["You must reauthenticate."], "accounts": []})

    result = normalize_simplefin(pull_from_text(body), UTC_TZ)

    assert result.batch is not None
    assert result.batch.errors == [PullError(code="legacy", message="You must reauthenticate.")]


def test_v1_connection_key_prefers_domain_then_id_then_sfin_url() -> None:
    def key(org: dict[str, str]) -> str:
        account = {"org": org, "id": "a", "name": "A", "currency": "USD", "balance": "0"}
        body = json.dumps({"errors": [], "accounts": [account]})
        result = normalize_simplefin(pull_from_text(body), UTC_TZ)
        assert result.batch is not None
        return result.batch.connections[0].provider_key

    assert key({"domain": "bank.example", "id": "ORG-1", "sfin-url": "https://s"}) == "bank.example"
    assert key({"id": "ORG-1", "sfin-url": "https://s"}) == "ORG-1"
    assert key({"sfin-url": "https://s"}) == "https://s"


def test_numeric_amount_keeps_exact_value_and_raw_text() -> None:
    batch = _normalize("simplefin_numeric_amount.json")

    txn = batch.transactions[0]
    assert txn.amount == Decimal("-5.10")
    assert '"amount":-5.10' in txn.raw  # exact text, not -5.1
    assert '"fee":1.10' in txn.raw


# --- v2 --------------------------------------------------------------------


def test_v2_fixture_normalizes() -> None:
    batch = _normalize("simplefin_v2_demo.json")

    assert (batch.source, batch.dialect) == ("simplefin", "v2")
    assert [(c.provider_key, c.name, c.org_id) for c in batch.connections] == [
        ("CON-A", "Demo Bank - Alex", "INST-DEMO"),
        ("CON-B", "Demo Bank - Sam", "INST-DEMO"),
    ]
    # The same account id exists under both connections.
    assert [(a.connection_key, a.external_id) for a in batch.accounts] == [
        ("CON-A", "chk-001"),
        ("CON-B", "chk-001"),
    ]
    assert batch.errors == [
        PullError(
            code="con.auth",
            message="Authentication required for Demo Bank - Sam",
            connection_key="CON-B",
        )
    ]
    first = batch.accounts[0]
    assert first.balance == Decimal("1500.00")
    assert first.available_balance == Decimal("1400.00")
    assert first.balance_as_of == datetime(2026, 3, 31, 12, 0, tzinfo=UTC)
    assert batch.accounts[1].available_balance is None


def test_pending_posted_zero_has_no_posted_date_and_keeps_transacted_date() -> None:
    batch = _normalize("simplefin_v2_demo.json")

    pending = _txn(batch, "txn-002")

    assert pending.pending
    assert pending.posted_date is None
    assert pending.transacted_date == date(2026, 3, 30)  # from transacted_at, in UTC


def test_transacted_at_sets_transacted_date_and_is_optional() -> None:
    batch = _normalize("simplefin_v2_demo.json")

    assert _txn(batch, "txn-001", "CON-A").transacted_date == date(2026, 3, 9)
    assert _txn(batch, "txn-001", "CON-B").transacted_date == date(2026, 3, 11)
    assert _txn(batch, "txn-003").transacted_date is None


# --- local dates -----------------------------------------------------------


def test_dates_are_the_users_local_date_not_utc() -> None:
    # cc-txn-009 posted 2026-04-01 00:00:00 UTC; cc-txn-001 posted 2026-02-28 23:59:59 UTC.
    utc = _normalize("simplefin_demo.json", UTC_TZ)
    new_york = _normalize("simplefin_demo.json", NEW_YORK)
    kolkata = _normalize("simplefin_demo.json", KOLKATA)

    assert _txn(utc, "cc-txn-009").posted_date == date(2026, 4, 1)
    assert _txn(new_york, "cc-txn-009").posted_date == date(2026, 3, 31)
    assert _txn(utc, "cc-txn-001").posted_date == date(2026, 2, 28)
    assert _txn(kolkata, "cc-txn-001").posted_date == date(2026, 3, 1)


def test_local_date_across_dst_boundaries() -> None:
    # 2026-03-09 04:30 UTC is 00:30 EDT on Mar 9 (clocks sprang forward on Mar 8).
    spring = int(datetime(2026, 3, 9, 4, 30, tzinfo=UTC).timestamp())
    # 2026-11-02 04:59 UTC is 23:59 EST on Nov 1 (clocks fell back on Nov 1).
    fall = int(datetime(2026, 11, 2, 4, 59, tzinfo=UTC).timestamp())

    assert local_date(spring, NEW_YORK) == date(2026, 3, 9)
    assert local_date(fall, NEW_YORK) == date(2026, 11, 1)


def test_zero_and_missing_timestamps_have_no_date() -> None:
    assert local_date(0, UTC_TZ) is None
    assert local_date(None, UTC_TZ) is None


# --- currency --------------------------------------------------------------


def test_custom_currency_is_flagged_and_never_fetched() -> None:
    account = {
        "org": {"domain": "airline.example"},
        "id": "miles",
        "name": "Miles",
        "currency": "https://airline.example/miles",
        "balance": "1200",
    }
    body = json.dumps({"errors": [], "accounts": [account]})

    result = normalize_simplefin(pull_from_text(body), UTC_TZ)

    assert result.batch is not None
    assert result.batch.accounts[0].currency_kind == "custom"
    assert result.batch.accounts[0].currency == "https://airline.example/miles"
    assert _normalize("simplefin_demo.json").accounts[0].currency_kind == "iso"


# --- bad input never raises ------------------------------------------------


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b"not json", "invalid"),
        (b'{"accounts": NaN}', "invalid"),
        (b"\xff\xfe\x00", "invalid"),
        (b'{"hello": 1}', "unrecognized"),
        (b"[]", "unrecognized"),
    ],
)
def test_unusable_bodies_return_a_status(body: bytes, expected: str) -> None:
    result = normalize_simplefin(pull_from_text(body), UTC_TZ)

    assert result.status == expected
    assert result.batch is None


def test_v1_account_without_org_is_invalid() -> None:
    body = json.dumps(
        {
            "errors": [],
            "accounts": [
                {
                    "org": {"domain": "a.example"},
                    "id": "1",
                    "name": "A",
                    "currency": "USD",
                    "balance": "0",
                },
                {"id": "2", "name": "B", "currency": "USD", "balance": "0"},
            ],
        }
    )

    result = normalize_simplefin(pull_from_text(body), UTC_TZ)

    assert result.status == "invalid"
    assert "no org" in (result.message or "")


def test_v2_account_with_unknown_connection_is_invalid() -> None:
    account = {"id": "1", "name": "A", "currency": "USD", "balance": "0", "conn_id": "NOPE"}
    body = json.dumps({"errlist": [], "connections": [], "accounts": [account]})

    result = normalize_simplefin(pull_from_text(body), UTC_TZ)

    assert result.status == "invalid"


def test_validation_message_names_fields_but_never_values() -> None:
    txn = {"id": "t", "posted": 1, "amount": "not-a-number", "description": "SECRET-MERCHANT-9921"}
    account = {
        "org": {"domain": "a.example"},
        "id": "1",
        "name": "A",
        "currency": "USD",
        "balance": "0",
        "transactions": [txn],
    }
    body = json.dumps({"errors": [], "accounts": [account]})

    result = normalize_simplefin(pull_from_text(body), UTC_TZ)

    assert result.status == "invalid"
    assert "amount" in (result.message or "")
    assert "not-a-number" not in (result.message or "")
    assert "SECRET-MERCHANT" not in (result.message or "")


@pytest.mark.parametrize("amount", ['"-1.50"', "-1.50"])
def test_amounts_are_decimal_whether_string_or_number(amount: str) -> None:
    body = (
        '{"errors": [], "accounts": [{"org": {"domain": "a.example"}, "id": "1", "name": "A",'
        ' "currency": "USD", "balance": "0", "transactions": [{"id": "t", "posted": 1,'
        f' "amount": {amount}, "description": "d"}}]}}]}}'
    )

    result = normalize_simplefin(pull_from_text(body), UTC_TZ)

    assert result.batch is not None
    assert result.batch.transactions[0].amount == Decimal("-1.50")


# --- request parameters ----------------------------------------------------


def test_request_params_default_asks_for_pending() -> None:
    assert simplefin_request_params(2) == {"version": "2", "pending": "1"}


def test_request_params_with_window_and_no_pending() -> None:
    start = datetime(2026, 3, 1, tzinfo=UTC)
    end = datetime(2026, 4, 1, tzinfo=UTC)

    params = simplefin_request_params(1, start=start, end=end, include_pending=False)

    assert params == {"version": "1", "start-date": "1772323200", "end-date": "1775001600"}


def test_request_params_reject_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        simplefin_request_params(2, start=datetime(2026, 3, 1))


# --- clients ---------------------------------------------------------------


def test_fixture_client_returns_the_exact_bytes_and_metadata() -> None:
    path = FIXTURES / "simplefin_demo.json"

    pull = FixtureSimpleFinClient(
        path, FETCHED_AT, requested_version="1", request_params={"version": "1"}
    ).fetch()

    assert pull.body == path.read_bytes()
    assert (pull.source, pull.fetched_at) == ("simplefin", FETCHED_AT)
    assert (pull.requested_version, pull.request_params) == ("1", {"version": "1"})


def test_live_client_is_still_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        LiveSimpleFinClient().fetch()


def test_no_network_libraries_in_the_ingest_package() -> None:
    forbidden = ("requests", "httpx", "urllib", "socket", "aiohttp")
    root = Path(__file__).resolve().parent.parent / "src" / "finance_agent"
    for path in [*root.glob("ingest/**/*.py"), root / "clients" / "simplefin.py"]:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert f"import {name}" not in source, f"{path.name} imports {name}"
            assert f"from {name}" not in source, f"{path.name} imports {name}"
