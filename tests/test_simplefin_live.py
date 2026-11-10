"""Live SimpleFIN connector: token claim, guarded fetch, and secret-containment.

Everything here uses fakes: a scripted ``FakeTransport`` for the client's control flow and
``httpx.MockTransport`` for the real streaming transport. No network, no keychain, no DB.
The sentinel strings must never appear in a returned value, a stored param or an exception.
"""

import base64
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from finance_agent.ingest.simplefin.client import (
    LiveSimpleFinClient,
    claim_access_url,
)
from finance_agent.ingest.simplefin.errors import (
    AccessRevoked,
    BankUnavailable,
    ClaimFailed,
    DestinationNotAllowed,
    MalformedSetupToken,
    ResponseTooLarge,
    TokenAlreadyClaimed,
    UnsafeClaimUrl,
)
from finance_agent.ingest.simplefin.request import simplefin_request_params
from finance_agent.ingest.simplefin.transport import (
    HttpxBankTransport,
    Response,
    guarded_get,
)

SENTINEL_USER = "SENTINEL-USER-9921"
SENTINEL_PASS = "SENTINEL-ACCESS-URL-9921"
ACCESS_URL = f"https://{SENTINEL_USER}:{SENTINEL_PASS}@bank.example.com/simplefin"
CLAIM_URL = "https://setup.example.com/claim/opaque-id"
SETUP_TOKEN = base64.b64encode(CLAIM_URL.encode()).decode()
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


class FakeTransport:
    """Records calls and returns scripted responses (or raises a scripted error)."""

    def __init__(self, response: Response | Exception) -> None:
        self._response = response
        self.calls: list[tuple[str, str, tuple[str, str] | None, bytes | None]] = []

    def get(self, url: str, auth: tuple[str, str] | None, timeout: float) -> Response:
        self.calls.append(("GET", url, auth, None))
        return self._out()

    def post(self, url: str, body: bytes, timeout: float) -> Response:
        self.calls.append(("POST", url, None, body))
        return self._out()

    def _out(self) -> Response:
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


# ---- token claim -----------------------------------------------------------------


def test_claim_returns_access_url_and_posts_to_claim_host() -> None:
    transport = FakeTransport(Response(200, ACCESS_URL.encode()))
    assert claim_access_url(SETUP_TOKEN, transport) == ACCESS_URL
    assert transport.calls == [("POST", CLAIM_URL, None, b"")]


def test_malformed_token_stores_nothing_and_never_calls_the_bank() -> None:
    transport = FakeTransport(Response(200, ACCESS_URL.encode()))
    with pytest.raises(MalformedSetupToken):
        claim_access_url("not-base64-!!!", transport)
    assert transport.calls == []


def test_non_https_claim_url_is_refused() -> None:
    token = base64.b64encode(b"http://setup.example.com/claim/x").decode()
    transport = FakeTransport(Response(200, ACCESS_URL.encode()))
    with pytest.raises(UnsafeClaimUrl):
        claim_access_url(token, transport)
    assert transport.calls == []


def test_already_claimed_token_gives_a_distinct_message() -> None:
    transport = FakeTransport(Response(403, b"Forbidden"))
    with pytest.raises(TokenAlreadyClaimed):
        claim_access_url(SETUP_TOKEN, transport)


def test_claim_server_error_is_retryable_but_a_4xx_is_not() -> None:
    with pytest.raises(BankUnavailable) as five:
        claim_access_url(SETUP_TOKEN, FakeTransport(Response(503, b"")))
    assert five.value.retryable is True
    with pytest.raises(ClaimFailed):
        claim_access_url(SETUP_TOKEN, FakeTransport(Response(400, b"")))


def test_claim_with_garbage_access_url_fails_cleanly() -> None:
    with pytest.raises(ClaimFailed):
        claim_access_url(SETUP_TOKEN, FakeTransport(Response(200, b"not a url")))


# ---- fetch -----------------------------------------------------------------------


def test_fetch_builds_accounts_url_passes_auth_and_keeps_url_credential_free() -> None:
    transport = FakeTransport(Response(200, b'{"accounts": []}'))
    client = LiveSimpleFinClient(ACCESS_URL, NOW, version=2, transport=transport)
    pull = client.fetch()

    method, url, auth, _ = transport.calls[0]
    assert method == "GET"
    assert url.startswith("https://bank.example.com/simplefin/accounts?")
    assert auth == (SENTINEL_USER, SENTINEL_PASS)
    # The credential-bearing URL never appears in the request line or the stored params.
    assert SENTINEL_PASS not in url
    assert pull.body == b'{"accounts": []}'
    assert pull.source == "simplefin"
    assert SENTINEL_PASS not in str(pull.request_params)
    assert "version" in pull.request_params


def test_fetch_redirect_is_refused_not_followed() -> None:
    client = LiveSimpleFinClient(ACCESS_URL, NOW, transport=FakeTransport(Response(302, b"")))
    with pytest.raises(DestinationNotAllowed):
        client.fetch()


def test_fetch_403_tells_user_to_reconnect() -> None:
    client = LiveSimpleFinClient(ACCESS_URL, NOW, transport=FakeTransport(Response(403, b"")))
    with pytest.raises(AccessRevoked) as err:
        client.fetch()
    assert err.value.retryable is False


def test_fetch_5xx_and_429_are_retryable() -> None:
    for status in (500, 503, 429):
        client = LiveSimpleFinClient(
            ACCESS_URL, NOW, transport=FakeTransport(Response(status, b""))
        )
        with pytest.raises(BankUnavailable) as err:
            client.fetch()
        assert err.value.retryable is True


# ---- guard: host pinning ---------------------------------------------------------


def test_guard_refuses_a_different_host() -> None:
    transport = FakeTransport(Response(200, b"{}"))
    with pytest.raises(DestinationNotAllowed):
        guarded_get(transport, "bank.example.com:443", "https://evil.example.com/accounts", None, 5)
    assert transport.calls == []


# ---- real streaming transport via httpx.MockTransport ----------------------------


def _httpx_transport(
    handler: Callable[[httpx.Request], httpx.Response], max_bytes: int = 32 * 1024 * 1024
) -> HttpxBankTransport:
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    return HttpxBankTransport(client=client, max_bytes=max_bytes)


def test_transport_caps_oversized_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 2048)

    transport = _httpx_transport(handler, max_bytes=1024)
    with pytest.raises(ResponseTooLarge):
        transport.get("https://bank.example.com/simplefin/accounts", None, 5)


def test_transport_does_not_follow_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://evil.example.com/"})

    resp = _httpx_transport(handler).get("https://bank.example.com/x", None, 5)
    assert resp.status == 302  # returned, not followed


def test_transport_timeout_hides_the_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout(f"timed out talking to {ACCESS_URL}")

    with pytest.raises(BankUnavailable) as err:
        _httpx_transport(handler).get(ACCESS_URL, (SENTINEL_USER, SENTINEL_PASS), 5)
    assert SENTINEL_PASS not in str(err.value)
    assert ACCESS_URL not in str(err.value)


# ---- request params --------------------------------------------------------------


def test_balances_only_param_is_exact() -> None:
    assert simplefin_request_params(2, balances_only=True, include_pending=False) == {
        "version": "2",
        "balances-only": "1",
    }
