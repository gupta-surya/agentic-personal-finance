"""Model settings, read from the environment. Nothing here is hardcoded to a host."""

import ipaddress
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self
from urllib.parse import urlsplit

from finance_agent.model_gateway.errors import ConfigError

DEFAULT_ENDPOINT = "http://localhost:11434"
DEFAULT_MODEL = "qwen3:8b"
DEFAULT_TIMEOUT_SECONDS = 60.0
_DEFAULT_PORTS = {"http": 80, "https": 443}


@dataclass(frozen=True)
class Endpoint:
    url: str  # scheme://host:port, no trailing slash
    host: str  # lowercase
    port: int

    @property
    def authority(self) -> str:
        return f"{self.host}:{self.port}"


# A DNS label sequence or an IP literal, nothing else: no backslash, percent, space or control
# characters, so the guard and httpx cannot read the same string as two different hosts.
_HOST = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$"
)


def _valid_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return bool(_HOST.fullmatch(host.lower())) and host.isascii()


def parse_endpoint(name: str, value: str) -> Endpoint:
    """Parse ``value`` as a bare http(s) origin. ``name`` is only used in the error text:
    the value itself is never echoed."""
    try:
        parts = urlsplit(value.strip())
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise ConfigError(f"{name} is not a valid URL") from None
    if parts.scheme not in _DEFAULT_PORTS or not host or not _valid_host(host):
        raise ConfigError(f"{name} must be an http(s) URL with a plain host name or IP")
    if port == 0:
        raise ConfigError(f"{name} has an invalid port")
    if (
        parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or parts.path not in ("", "/")
    ):
        raise ConfigError(f"{name} must be a bare origin: no credentials, path or query")
    port = port or _DEFAULT_PORTS[parts.scheme]
    return Endpoint(url=f"{parts.scheme}://{_bracket(host)}:{port}", host=host.lower(), port=port)


def authority_of(url: str) -> str:
    """``host:port`` of any http(s) URL, for comparing a request against the pinned set."""
    try:
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError:
        raise ConfigError("request URL is not valid") from None
    if parts.scheme not in _DEFAULT_PORTS or not host or not _valid_host(host) or port == 0:
        raise ConfigError("request URL must be http(s) with a plain host")
    return f"{host.lower()}:{port or _DEFAULT_PORTS[parts.scheme]}"


def _bracket(host: str) -> str:
    return f"[{host}]" if ":" in host else host


def _is_lan_host(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "." not in host or host.endswith((".local", ".lan", ".home.arpa"))
    return ip.is_private or ip.is_loopback or ip.is_link_local


@dataclass(frozen=True)
class ModelConfig:
    endpoint: Endpoint
    model: str = DEFAULT_MODEL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    remote_endpoint: Endpoint | None = None
    remote_model: str | None = None
    # At most one ``host:port``, equal to ``endpoint``: the operator's explicit opt-in to a
    # LAN model server. Raw line items flow to it, so it is pinned, never a pattern.
    pinned_lan_host: str | None = None
    remote_jobs: frozenset[str] = frozenset()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Self:
        env = os.environ if env is None else env
        endpoint = parse_endpoint("MODEL_ENDPOINT", env.get("MODEL_ENDPOINT") or DEFAULT_ENDPOINT)

        timeout = DEFAULT_TIMEOUT_SECONDS
        if raw := env.get("MODEL_TIMEOUT_SECONDS"):
            try:
                timeout = float(raw)
            except ValueError:
                raise ConfigError("MODEL_TIMEOUT_SECONDS must be a number") from None
            if not 0 < timeout <= 600:
                raise ConfigError("MODEL_TIMEOUT_SECONDS must be between 0 and 600")

        remote = None
        if raw := env.get("REMOTE_MODEL_ENDPOINT"):
            remote = parse_endpoint("REMOTE_MODEL_ENDPOINT", raw)
            if not remote.url.startswith("https://"):
                raise ConfigError("REMOTE_MODEL_ENDPOINT must be https")

        pinned = None
        if raw := env.get("LOCAL_MODEL_HOSTS"):
            entries = [e.strip().lower() for e in raw.split(",") if e.strip()]
            if len(entries) != 1:
                raise ConfigError("LOCAL_MODEL_HOSTS must name exactly one host:port")
            if entries[0] != endpoint.authority:
                raise ConfigError("LOCAL_MODEL_HOSTS must equal the MODEL_ENDPOINT host:port")
            if not _is_lan_host(endpoint.host):
                raise ConfigError(
                    "LOCAL_MODEL_HOSTS must be a private or link-local IP, or a .local/.lan/"
                    "single-label name: a public host is not a LAN server"
                )
            pinned = entries[0]

        jobs = frozenset(
            j.strip() for j in env.get("REMOTE_MODEL_JOBS", "").split(",") if j.strip()
        )
        return cls(
            endpoint=endpoint,
            model=env.get("MODEL_NAME") or DEFAULT_MODEL,
            timeout_seconds=timeout,
            remote_endpoint=remote,
            remote_model=env.get("REMOTE_MODEL_NAME") or None,
            pinned_lan_host=pinned,
            remote_jobs=jobs,
        )
