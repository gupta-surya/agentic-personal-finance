"""The one model client. Ollama's native ``/api/chat`` with ``format`` set to the schema."""

import json
from collections.abc import Sequence

from pydantic import BaseModel

from finance_agent.model_gateway.config import ModelConfig
from finance_agent.model_gateway.errors import ModelRequestRejected, ModelUnavailable
from finance_agent.model_gateway.routing import Job, Router
from finance_agent.model_gateway.structured import Message, generate_structured
from finance_agent.model_gateway.transport import GuardedTransport, HttpxTransport, Transport


def guarded(config: ModelConfig, transport: Transport | None = None) -> GuardedTransport:
    return GuardedTransport(transport or HttpxTransport(), Router(config).authorities())


class ModelGateway:
    """``generate(job, messages, schema)`` returns a validated ``schema`` instance or raises
    ``ModelUnavailable`` / ``ModelOutputInvalid``. Both call sites use this and nothing else."""

    def __init__(self, config: ModelConfig, transport: Transport | None = None) -> None:
        self._config = config
        self._router = Router(config)
        self._transport = GuardedTransport(
            transport or HttpxTransport(), self._router.authorities()
        )

    def generate[T: BaseModel](self, job: Job, messages: Sequence[Message], schema: type[T]) -> T:
        route = self._router.route(job)
        schema_json = schema.model_json_schema()

        def send(convo: Sequence[Message]) -> str:
            body = json.dumps(
                {
                    "model": route.model,
                    "messages": list(convo),
                    "stream": False,
                    "think": False,  # reasoning text wastes time and can break constrained output
                    "format": schema_json,
                    "options": {"temperature": 0},
                }
            ).encode()
            resp = self._transport.post(
                f"{route.endpoint.url}/api/chat", body, self._config.timeout_seconds
            )
            if resp.status >= 500:
                raise ModelUnavailable(f"model endpoint failed (HTTP {resp.status})")
            if resp.status >= 400:
                raise ModelRequestRejected(
                    f"model endpoint rejected the request (HTTP {resp.status})"
                )
            try:
                content = json.loads(resp.body)["message"]["content"]
            except (ValueError, KeyError, TypeError):
                raise ModelUnavailable("model endpoint sent an unreadable reply") from None
            if not isinstance(content, str):
                raise ModelUnavailable("model endpoint sent an unreadable reply")
            return content

        return generate_structured(send, messages, schema)
