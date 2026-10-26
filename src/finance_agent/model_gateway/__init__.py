"""The one gateway to the local model (DESIGN §6). Used by exactly two call sites, neither
built yet: novel-merchant categorization (TASK-04b) and the interactive agent (Phase 4).

Nothing in ``ingest/``, ``categorize/``, ``reconcile/``, ``queries/`` or ``db/`` may import
this package; a test enforces it.
"""

from finance_agent.model_gateway.client import ModelGateway
from finance_agent.model_gateway.config import ModelConfig
from finance_agent.model_gateway.errors import (
    ConfigError,
    DestinationNotAllowed,
    ModelGatewayError,
    ModelOutputInvalid,
    ModelRequestRejected,
    ModelUnavailable,
)
from finance_agent.model_gateway.health import ModelStatus, check, model_status_signal
from finance_agent.model_gateway.routing import DataClass, Job
from finance_agent.model_gateway.structured import Message

__all__ = [
    "ConfigError",
    "DataClass",
    "DestinationNotAllowed",
    "Job",
    "Message",
    "ModelConfig",
    "ModelGateway",
    "ModelGatewayError",
    "ModelOutputInvalid",
    "ModelRequestRejected",
    "ModelStatus",
    "ModelUnavailable",
    "check",
    "model_status_signal",
]
