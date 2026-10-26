"""A transport that talks to nothing: tests see the exact payloads the gateway would send."""

import json
from collections.abc import Callable
from typing import Any

from finance_agent.model_gateway.config import ModelConfig, authority_of
from finance_agent.model_gateway.transport import Response

Handler = Callable[[dict[str, Any]], Response | Exception]

LOCAL = ModelConfig.from_env({})


def ok(content: str) -> Response:
    return Response(
        200, json.dumps({"message": {"role": "assistant", "content": content}}).encode()
    )


class FakeTransport:
    def __init__(self, post: Handler | list[Response | Exception] | None = None) -> None:
        self._post = post
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.gets: list[str] = []
        self.get_replies: dict[str, Response | Exception] = {}

    def post(self, url: str, body: bytes, timeout: float) -> Response:
        payload = json.loads(body)
        self.posts.append((url, payload))
        reply = self._post(payload) if callable(self._post) else (self._post or []).pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def get(self, url: str, timeout: float) -> Response:
        self.gets.append(url)
        reply = self.get_replies.get(url.rsplit("/api/", 1)[1], Response(404, b""))
        if isinstance(reply, Exception):
            raise reply
        return reply

    @property
    def hosts(self) -> set[str]:
        return {authority_of(url) for url, _ in self.posts} | {authority_of(u) for u in self.gets}
