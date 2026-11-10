"""Host/authority parsing for the outbound guards.

Both the model gateway and the bank connector must pin a request to one host. The data
pipeline (``ingest/`` etc.) must not import the model gateway, so the shared, dependency-free
host check lives here and both import it from here.
"""

import ipaddress
import re
from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}
# A DNS label sequence or an IP literal, nothing else: no backslash, percent, space or
# control characters, so the guard and the HTTP client cannot read one string as two hosts.
_HOST = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$"
)


class NetlocError(ValueError):
    """A URL is not a plain http(s) origin a host can be pinned from."""


def valid_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return bool(_HOST.fullmatch(host.lower())) and host.isascii()


def authority_of(url: str) -> str:
    """``host:port`` of an http(s) URL, for comparing a request against the pinned host."""
    try:
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError:
        raise NetlocError("request URL is not valid") from None
    if parts.scheme not in _DEFAULT_PORTS or not host or not valid_host(host) or port == 0:
        raise NetlocError("request URL must be http(s) with a plain host")
    return f"{host.lower()}:{port or _DEFAULT_PORTS[parts.scheme]}"
