"""HTTP transport, and the guard that pins it to the configured endpoints."""

from dataclasses import dataclass
from typing import Protocol

import httpx

from finance_agent.model_gateway.audit import record_outbound
from finance_agent.model_gateway.config import authority_of
from finance_agent.model_gateway.errors import DestinationNotAllowed, ModelUnavailable

MAX_RESPONSE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes


class Transport(Protocol):
    def get(self, url: str, timeout: float) -> Response: ...

    def post(self, url: str, body: bytes, timeout: float) -> Response: ...


class HttpxTransport:
    """Plain httpx. Redirects are never followed: a redirect is another destination."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(follow_redirects=False, trust_env=False)

    def get(self, url: str, timeout: float) -> Response:
        return self._send("GET", url, None, timeout)

    def post(self, url: str, body: bytes, timeout: float) -> Response:
        return self._send("POST", url, body, timeout)

    def _send(self, method: str, url: str, body: bytes | None, timeout: float) -> Response:
        try:
            with self._client.stream(
                method,
                url,
                content=body,
                timeout=timeout,
                headers={"content-type": "application/json"} if body is not None else None,
            ) as resp:
                if 300 <= resp.status_code < 400:
                    raise DestinationNotAllowed("model endpoint tried to redirect; refused")
                data = bytearray()
                for chunk in resp.iter_bytes():
                    data += chunk
                    if len(data) > MAX_RESPONSE_BYTES:
                        raise ModelUnavailable("model endpoint reply is too large")
                return Response(resp.status_code, bytes(data))
        except (httpx.HTTPError, httpx.InvalidURL):  # refused, timeout, reset, bad encoding
            raise ModelUnavailable("model endpoint is unreachable") from None


class GuardedTransport:
    """Deny by default: only requests to an allowed ``host:port`` reach the inner transport."""

    def __init__(self, inner: Transport, allowed: frozenset[str]) -> None:
        self._inner = inner
        self._allowed = allowed

    def _check(self, url: str, size: int) -> None:
        authority = authority_of(url)
        if authority not in self._allowed:
            raise DestinationNotAllowed("request is not aimed at a configured model endpoint")
        record_outbound(authority, size)

    def get(self, url: str, timeout: float) -> Response:
        self._check(url, 0)
        return self._inner.get(url, timeout)

    def post(self, url: str, body: bytes, timeout: float) -> Response:
        self._check(url, len(body))
        return self._inner.post(url, body, timeout)
