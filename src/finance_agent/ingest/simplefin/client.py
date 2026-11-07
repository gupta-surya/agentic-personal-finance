"""SimpleFIN connector clients: they fetch bytes and request metadata, nothing more.

Parsing lives in ``finance_agent.ingest.simplefin``. Tests only ever use
``FixtureSimpleFinClient``. ``LiveSimpleFinClient`` is a stub with no network code
in it; it must stay that way until the live connector task.
"""

from datetime import datetime
from pathlib import Path
from typing import Protocol

from finance_agent.ingest.contract import RawPull


class SimpleFinClient(Protocol):
    def fetch(self) -> RawPull:
        """Return the exact response bytes and how they were requested."""
        ...


class FixtureSimpleFinClient:
    def __init__(
        self,
        path: Path,
        fetched_at: datetime,
        requested_version: str | None = None,
        request_params: dict[str, str] | None = None,
    ) -> None:
        self._path = path
        self._fetched_at = fetched_at  # explicit: logic never reads the wall clock
        self._requested_version = requested_version
        self._request_params = request_params or {}

    def fetch(self) -> RawPull:
        return RawPull(
            source="simplefin",
            body=self._path.read_bytes(),
            fetched_at=self._fetched_at,
            requested_version=self._requested_version,
            request_params=self._request_params,
        )


class LiveSimpleFinClient:
    def fetch(self) -> RawPull:
        raise NotImplementedError("live SimpleFIN access is not implemented")
