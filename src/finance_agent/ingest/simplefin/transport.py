"""Guarded HTTP for the SimpleFIN connector: one pinned host, no redirects, a size cap.

The product has no general web access (invariant 2); this is the single bank
connector, and it may talk only to the host inside the user's access URL. The
guard mirrors the model gateway's: redirects are never followed (a redirect is
another destination), the environment's proxy settings are ignored
(``trust_env=False``), the response body is capped, and every request's host is
checked against the pinned authority before it is sent. Credentials travel only
in the ``auth`` argument, never in a URL the transport logs.
"""

from dataclasses import dataclass
from typing import Protocol

import httpx

from finance_agent.ingest.simplefin.errors import (
    BankUnavailable,
    DestinationNotAllowed,
    ResponseTooLarge,
)
from finance_agent.model_gateway.config import authority_of
from finance_agent.model_gateway.errors import ConfigError

MAX_RESPONSE_BYTES = 32 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 60.0

Auth = tuple[str, str]


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes


class Transport(Protocol):
    def get(self, url: str, auth: Auth | None, timeout: float) -> Response: ...

    def post(self, url: str, body: bytes, timeout: float) -> Response: ...


class HttpxBankTransport:
    """Plain httpx, streamed so an oversized body is cut off instead of buffered whole.
    Redirects are never followed and the environment is never trusted."""

    def __init__(
        self, client: httpx.Client | None = None, max_bytes: int = MAX_RESPONSE_BYTES
    ) -> None:
        self._client = client or httpx.Client(follow_redirects=False, trust_env=False)
        self._max_bytes = max_bytes

    def get(self, url: str, auth: Auth | None, timeout: float) -> Response:
        return self._send("GET", url, None, auth, timeout)

    def post(self, url: str, body: bytes, timeout: float) -> Response:
        return self._send("POST", url, body, None, timeout)

    def _send(
        self, method: str, url: str, body: bytes | None, auth: Auth | None, timeout: float
    ) -> Response:
        try:
            with self._client.stream(method, url, content=body, auth=auth, timeout=timeout) as resp:
                chunks = bytearray()
                for chunk in resp.iter_bytes():
                    chunks += chunk
                    if len(chunks) > self._max_bytes:
                        raise ResponseTooLarge(
                            "the bank's response was unexpectedly large and was refused"
                        )
                return Response(resp.status_code, bytes(chunks))
        except httpx.HTTPError:
            # The exception text can carry the URL (with credentials); never propagate it.
            raise BankUnavailable("could not reach your bank; try again later") from None


def guarded_get(
    transport: Transport, authority: str, url: str, auth: Auth | None, timeout: float
) -> Response:
    _require_authority(authority, url)
    return transport.get(url, auth, timeout)


def guarded_post(
    transport: Transport, authority: str, url: str, body: bytes, timeout: float
) -> Response:
    _require_authority(authority, url)
    return transport.post(url, body, timeout)


def _require_authority(authority: str, url: str) -> None:
    try:
        target = authority_of(url)
    except ConfigError:
        raise DestinationNotAllowed("refused a request to an unexpected destination") from None
    if target != authority:
        raise DestinationNotAllowed("refused a request to an unexpected host")
