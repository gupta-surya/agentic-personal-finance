"""SimpleFIN connector clients: they fetch bytes and request metadata, nothing more.

Parsing lives in ``finance_agent.ingest.simplefin``. Tests use ``FixtureSimpleFinClient``.
``LiveSimpleFinClient`` and ``claim_access_url`` are the only code that talks to the bank;
they go through the guarded transport (one pinned host, no redirects, size cap) and never
let the setup token or the credential-bearing access URL reach a log, an exception or a
stored row (invariant 8).
"""

import base64
import binascii
from datetime import datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urlencode, urlsplit, urlunsplit

from finance_agent.ingest.contract import RawPull
from finance_agent.ingest.simplefin.errors import (
    AccessRevoked,
    BankUnavailable,
    ClaimFailed,
    DestinationNotAllowed,
    MalformedSetupToken,
    SimpleFinError,
    TokenAlreadyClaimed,
    UnsafeClaimUrl,
)
from finance_agent.ingest.simplefin.request import simplefin_request_params
from finance_agent.ingest.simplefin.transport import (
    DEFAULT_TIMEOUT_SECONDS,
    Auth,
    HttpxBankTransport,
    Transport,
    guarded_get,
    guarded_post,
)
from finance_agent.netloc import NetlocError, authority_of


class SimpleFinClient(Protocol):
    def fetch(self) -> RawPull:
        """Return the exact response bytes and how they were requested."""
        ...


class FixtureSimpleFinClient:
    def __init__(
        self,
        path: Path,
        fetched_at: datetime,
        requested_version: str | None = None,
        request_params: dict[str, str] | None = None,
    ) -> None:
        self._path = path
        self._fetched_at = fetched_at  # explicit: logic never reads the wall clock
        self._requested_version = requested_version
        self._request_params = request_params or {}

    def fetch(self) -> RawPull:
        return RawPull(
            source="simplefin",
            body=self._path.read_bytes(),
            fetched_at=self._fetched_at,
            requested_version=self._requested_version,
            request_params=self._request_params,
        )


class LiveSimpleFinClient:
    """Fetch one ``GET /accounts`` from the user's SimpleFIN access URL.

    The access URL embeds credentials; it is held only for the length of the fetch,
    passed in by the caller (from the encrypted credentials store, see
    ``finance_agent.credentials``), and never stored or logged. Only the safe query
    parameters reach the returned ``RawPull`` and, through it, bronze.
    """

    def __init__(
        self,
        access_url: str,
        fetched_at: datetime,
        *,
        version: int = 2,
        start: datetime | None = None,
        end: datetime | None = None,
        include_pending: bool = True,
        balances_only: bool = False,
        transport: Transport | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._access_url = access_url
        self._fetched_at = fetched_at
        self._version = version
        self._start = start
        self._end = end
        self._include_pending = include_pending
        self._balances_only = balances_only
        self._transport = transport or HttpxBankTransport()
        self._timeout = timeout

    def fetch(self) -> RawPull:
        base, auth, authority = _split_access_url(self._access_url)
        params = simplefin_request_params(
            self._version, self._start, self._end, self._include_pending, self._balances_only
        )
        resp = guarded_get(
            self._transport, authority, _accounts_url(base, params), auth, self._timeout
        )
        _check_fetch_status(resp.status)
        return RawPull(
            source="simplefin",
            body=resp.body,
            fetched_at=self._fetched_at,
            requested_version=str(self._version),
            request_params=params,
            http_status=resp.status,
        )


def claim_access_url(
    setup_token: str,
    transport: Transport | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Claim a one-time SimpleFIN setup token and return the access URL.

    The token is spent by this call and is not retained anywhere. The returned access URL
    carries credentials: the caller stores it with ``finance_agent.secrets`` and never logs
    it. Every failure raises a ``SimpleFinError`` whose message is safe to show.
    """
    transport = transport or HttpxBankTransport()
    claim_url = _decode_setup_token(setup_token)
    try:
        authority = authority_of(claim_url)
    except NetlocError:
        raise MalformedSetupToken("the setup token's claim URL is not valid") from None
    resp = guarded_post(transport, authority, claim_url, b"", timeout)
    _check_claim_status(resp.status)
    access_url = resp.body.decode("utf-8", "replace").strip()
    try:
        _split_access_url(access_url)  # validate shape only
    except SimpleFinError:
        raise ClaimFailed("the bank did not return a usable access URL") from None
    return access_url


def _decode_setup_token(setup_token: str) -> str:
    raw = setup_token.strip()
    if not raw:
        raise MalformedSetupToken("the setup token is empty")
    try:
        decoded = base64.b64decode(raw, validate=True).decode("utf-8").strip()
    except (binascii.Error, ValueError):
        raise MalformedSetupToken("that does not look like a SimpleFIN setup token") from None
    parts = urlsplit(decoded)
    if not parts.scheme or not parts.hostname:
        raise MalformedSetupToken("the setup token did not decode to a URL") from None
    if parts.scheme != "https":
        raise UnsafeClaimUrl("the setup token's claim URL must use https")
    return decoded


def _split_access_url(access_url: str) -> tuple[str, Auth | None, str]:
    """``(base_url_without_credentials, (user, password) | None, host:port)``."""
    parts = urlsplit(access_url.strip())
    if parts.scheme != "https" or not parts.hostname:
        raise AccessRevoked("your saved bank connection is invalid; reconnect it")
    auth: Auth | None = None
    if parts.username is not None:
        auth = (unquote(parts.username), unquote(parts.password or ""))
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    netloc = host if parts.port is None else f"{host}:{parts.port}"
    base = urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    try:
        authority = authority_of(base)
    except NetlocError:
        raise AccessRevoked("your saved bank connection is invalid; reconnect it") from None
    return base, auth, authority


def _accounts_url(base: str, params: dict[str, str]) -> str:
    return f"{base.rstrip('/')}/accounts?{urlencode(params)}"


def _check_claim_status(status: int) -> None:
    if 200 <= status < 300:
        return
    if 300 <= status < 400:
        raise DestinationNotAllowed("the claim was redirected to another location; refused")
    if status in (401, 403):
        raise TokenAlreadyClaimed(
            "this setup token was already used; create a new one in your bank"
        )
    if 500 <= status < 600:
        raise BankUnavailable("your bank is unavailable; try the setup again later")
    raise ClaimFailed("the setup token could not be claimed")


def _check_fetch_status(status: int) -> None:
    if 200 <= status < 300:
        return
    if 300 <= status < 400:
        raise DestinationNotAllowed("the bank redirected the request; refused")
    if status in (401, 403):
        raise AccessRevoked("your bank connection was rejected; reconnect it to refresh access")
    if status == 429 or 500 <= status < 600:
        raise BankUnavailable("your bank is busy or unavailable; try again later")
    raise BankUnavailable("your bank returned an unexpected response; try again later")
