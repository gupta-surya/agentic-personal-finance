"""Gateway errors. None of them ever carries a prompt or a model response: both can
contain merchant text, and errors end up in logs (CLAUDE.md invariant 8)."""


class ModelGatewayError(Exception):
    """Base class for everything the gateway raises."""


class ConfigError(ModelGatewayError, ValueError):
    """The model settings are missing, malformed or unsafe. Raised at startup."""


class ModelUnavailable(ModelGatewayError):
    """The endpoint cannot serve right now: refused, timed out, 5xx. Callers degrade to
    rules and show ``model_status_signal``."""


class ModelRequestRejected(ModelGatewayError):
    """The endpoint answered 4xx. That is a bug in our request, not an outage."""


class ModelOutputInvalid(ModelGatewayError):
    """The model's reply did not match the schema, after one repair retry."""

    def __init__(self, schema_name: str, detail: str) -> None:
        super().__init__(f"model output did not match {schema_name}: {detail}")
        self.schema_name = schema_name


class DestinationNotAllowed(ModelGatewayError):
    """A request was aimed somewhere other than a pinned model endpoint."""
