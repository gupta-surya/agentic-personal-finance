"""SimpleFIN connector: a typed model of the payload plus the client interface.

Tests only ever use ``FixtureSimpleFinClient``. ``LiveSimpleFinClient`` is a stub
with no network code in it; it must stay that way until the live connector task.
"""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SimpleFinOrg(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str | None = None
    domain: str | None = None


class SimpleFinTransaction(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    posted: int  # Unix epoch seconds
    amount: Decimal  # debits negative, credits positive (SimpleFIN convention)
    description: str
    pending: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("amount", mode="before")
    @classmethod
    def _reject_float(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("amount must be a decimal string, never a float")
        return value

    @property
    def category(self) -> str | None:
        # Synthetic-fixture shim: real SimpleFIN has no category field. Categorization
        # proper is not implemented yet.
        value = self.extra.get("category")
        return value if isinstance(value, str) else None


class SimpleFinAccount(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    currency: str
    balance: Decimal
    org: SimpleFinOrg = Field(default_factory=SimpleFinOrg)
    transactions: list[SimpleFinTransaction] = Field(default_factory=list)

    @field_validator("balance", mode="before")
    @classmethod
    def _reject_float(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("balance must be a decimal string, never a float")
        return value


class SimpleFinPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    errors: list[str] = Field(default_factory=list)
    accounts: list[SimpleFinAccount]


def parse_payload(body: str) -> SimpleFinPayload:
    """Parse a raw SimpleFIN JSON body. JSON numbers become Decimal, not float."""
    return SimpleFinPayload.model_validate(json.loads(body, parse_float=Decimal))


class SimpleFinClient(Protocol):
    def fetch(self) -> str:
        """Return the raw SimpleFIN account-set JSON body."""
        ...


class FixtureSimpleFinClient:
    def __init__(self, path: Path) -> None:
        self._path = path

    def fetch(self) -> str:
        return self._path.read_text(encoding="utf-8")


class LiveSimpleFinClient:
    def fetch(self) -> str:
        raise NotImplementedError("live SimpleFIN access is not implemented")
