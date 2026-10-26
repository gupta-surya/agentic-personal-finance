"""Which endpoint serves which job, and the rule that raw data stays local.

``raw`` jobs may carry merchant names, accounts or line items (CLAUDE.md invariant 3);
they can only resolve to a local endpoint. The check happens when the router is built, so
a bad configuration stops the app at startup instead of leaking on the first call.
"""

import ipaddress
from dataclasses import dataclass
from enum import StrEnum

from finance_agent.model_gateway.config import Endpoint, ModelConfig
from finance_agent.model_gateway.errors import ConfigError

LOCAL_NAMES = frozenset({"localhost", "host.docker.internal"})


class DataClass(StrEnum):
    RAW = "raw"
    AGGREGATE = "aggregate"


class Job(StrEnum):
    CATEGORIZE_MERCHANT = "categorize_merchant"
    AGENT_TURN = "agent_turn"
    # Prose around already-computed aggregates. Caller contract: the messages hold aggregates
    # only. The gateway cannot inspect them, so the only caller (the verifier-gated narrator)
    # must build them from QueryResult totals, never from rows.
    NARRATION = "narration"
    BENCHMARK = "benchmark"

    @property
    def data_class(self) -> DataClass:
        return DataClass.AGGREGATE if self is Job.NARRATION else DataClass.RAW


@dataclass(frozen=True)
class Route:
    endpoint: Endpoint
    model: str
    remote: bool


def is_local(endpoint: Endpoint, pinned_lan_host: str | None) -> bool:
    """Loopback or the host-reachable alias, or the one operator-pinned ``host:port``.

    Names are compared literally, never resolved: ``localhost.evil.example`` is not local.
    """
    if endpoint.host in LOCAL_NAMES:
        return True
    try:
        if ipaddress.ip_address(endpoint.host).is_loopback:
            return True
    except ValueError:
        pass
    return pinned_lan_host is not None and endpoint.authority == pinned_lan_host


class Router:
    def __init__(self, config: ModelConfig) -> None:
        unknown = config.remote_jobs - {j.value for j in Job}
        if unknown:
            raise ConfigError("REMOTE_MODEL_JOBS names an unknown job")
        local_ok = is_local(config.endpoint, config.pinned_lan_host)
        self._routes: dict[Job, Route] = {}
        for job in Job:
            if job.value in config.remote_jobs:
                if job.data_class is DataClass.RAW:
                    raise ConfigError(f"job {job.value} carries raw data and cannot go remote")
                if config.remote_endpoint is None:
                    raise ConfigError(f"job {job.value} is routed remote but no remote is set")
                self._routes[job] = Route(
                    config.remote_endpoint, config.remote_model or config.model, remote=True
                )
            else:
                if job.data_class is DataClass.RAW and not local_ok:
                    raise ConfigError(
                        f"MODEL_ENDPOINT is not local, but job {job.value} carries raw data; "
                        "set LOCAL_MODEL_HOSTS to that one host:port to opt in"
                    )
                self._routes[job] = Route(config.endpoint, config.model, remote=False)

    def route(self, job: Job) -> Route:
        return self._routes[job]

    def authorities(self) -> frozenset[str]:
        return frozenset(r.endpoint.authority for r in self._routes.values())
