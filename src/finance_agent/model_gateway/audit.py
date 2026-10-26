"""Outbound audit: where a request went and how big it was, never what it held."""

import logging

_log = logging.getLogger("finance_agent.model_gateway.audit")


def record_outbound(authority: str, byte_length: int) -> None:
    _log.debug("model request host=%s bytes=%d", authority, byte_length)
