"""Is the model there? A cheap check that never generates, and the text we show about it."""

import json
from dataclasses import dataclass

from finance_agent.model_gateway.client import guarded
from finance_agent.model_gateway.config import ModelConfig
from finance_agent.model_gateway.errors import ModelGatewayError
from finance_agent.model_gateway.transport import Transport


@dataclass(frozen=True)
class ModelStatus:
    available: bool
    model_present: bool
    endpoint: str  # for operators and logs; never shown to the user
    detail: str


def _installed(names: list[str], wanted: str) -> bool:
    return wanted in names or (":" not in wanted and f"{wanted}:latest" in names)


def check(config: ModelConfig, transport: Transport | None = None) -> ModelStatus:
    url = f"{config.endpoint.url}/api/tags"
    try:
        resp = guarded(config, transport).get(url, config.timeout_seconds)
        if resp.status != 200:
            return ModelStatus(False, False, config.endpoint.url, f"HTTP {resp.status}")
        names = [m["name"] for m in json.loads(resp.body)["models"]]
    except ModelGatewayError as err:
        return ModelStatus(False, False, config.endpoint.url, str(err))
    except (ValueError, KeyError, TypeError):
        return ModelStatus(False, False, config.endpoint.url, "unreadable reply")
    present = _installed(names, config.model)
    return ModelStatus(
        True, present, config.endpoint.url, "ok" if present else "model not installed"
    )


def server_version(config: ModelConfig, transport: Transport | None = None) -> str | None:
    try:
        resp = guarded(config, transport).get(
            f"{config.endpoint.url}/api/version", config.timeout_seconds
        )
        return str(json.loads(resp.body)["version"]) if resp.status == 200 else None
    except (ModelGatewayError, ValueError, KeyError, TypeError):
        return None


def model_status_signal(status: ModelStatus) -> str | None:
    """What the app tells the user, or None when all is well. No host, no data."""
    if not status.available:
        return "Model offline: new merchants stay uncategorized until it is back."
    if not status.model_present:
        return "Model not installed: new merchants stay uncategorized until it is."
    return None
