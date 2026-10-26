"""Schema-checked model output: validate, repair once, then fail."""

import re
from collections.abc import Callable, Sequence
from typing import Literal, TypedDict

from pydantic import BaseModel, ValidationError

from finance_agent.model_gateway.errors import ModelOutputInvalid


class Message(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,40}")


def _loc(parts: tuple[int | str, ...]) -> str:
    """Field names and list indexes only: a dict key the model chose could be merchant text."""
    return ".".join(str(p) if isinstance(p, int) or _FIELD.fullmatch(p) else "?" for p in parts)


def _describe(error: ValidationError) -> str:
    """Where and what kind, never the offending value (it may be merchant text)."""
    return "; ".join(
        f"{_loc(e['loc']) or 'output'}: {e['type']}"
        for e in error.errors(include_input=False, include_url=False, include_context=False)
    )


def generate_structured[T: BaseModel](
    send: Callable[[Sequence[Message]], str], messages: Sequence[Message], schema: type[T]
) -> T:
    """Constrained decoding guarantees shape, not content, and a model can still slip:
    parse the reply, and on failure ask once more with the problem stated."""
    convo = list(messages)
    first = send(convo)
    try:
        return schema.model_validate_json(first)
    except ValidationError as err:
        problem = _describe(err)
    convo += [
        {"role": "assistant", "content": first},
        {
            "role": "user",
            "content": f"That reply did not match the required schema ({problem}). "
            "Reply again with only JSON that matches it.",
        },
    ]
    second = send(convo)
    try:
        return schema.model_validate_json(second)
    except ValidationError as err:
        raise ModelOutputInvalid(schema.__name__, _describe(err)) from None
