"""The source-neutral contract between connectors and the silver loader.

A connector fetches a ``RawPull`` (exact bytes plus request metadata), and its
normalize step turns that into a ``NormalizedBatch``. The silver loader only ever
sees the batch, so adding a source (Plaid, CSV) means writing a new normalizer,
not touching the loader or the tables.

Sign convention (applied in each connector's normalize step and nowhere else):
debits are negative, credits are positive, and spend = -SUM(amount). Money is
``Decimal``; floats are rejected.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _reject_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("money must be a Decimal or decimal string, never a float")
    return value


Money = Annotated[Decimal, BeforeValidator(_reject_float)]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class RawPull(_Frozen):
    """Exactly what a connector received, plus how it was requested."""

    source: str
    body: bytes
    fetched_at: datetime  # supplied by the caller; logic never reads the wall clock
    requested_version: str | None = None
    request_params: dict[str, str] = Field(default_factory=dict)
    http_status: int | None = None
    server_versions: list[str] | None = None


class NormalizedConnection(_Frozen):
    """One login at one institution. ``provider_key`` is unique within a source."""

    provider_key: str
    name: str
    org_id: str | None = None
    org_url: str | None = None
    sfin_url: str | None = None


class NormalizedAccount(_Frozen):
    connection_key: str
    external_id: str  # unique only within its connection
    name: str
    currency: str
    currency_kind: Literal["iso", "custom"]
    balance: Money
    available_balance: Money | None = None
    balance_as_of: datetime | None = None


class NormalizedTransaction(_Frozen):
    connection_key: str
    account_external_id: str
    external_id: str  # unique within its account
    amount: Money  # signed: debit negative, credit positive
    description: str
    posted_date: date | None = None  # the user's local date; None while pending
    transacted_date: date | None = None  # the user's local date
    pending: bool = False
    category_hint: str | None = None  # a hint from the source, never a dependency
    raw: str  # the original object as JSON text, number text preserved


class PullError(_Frozen):
    code: str
    message: str
    connection_key: str | None = None
    account_external_id: str | None = None


class NormalizedBatch(_Frozen):
    source: str
    dialect: str
    connections: list[NormalizedConnection]
    accounts: list[NormalizedAccount]
    transactions: list[NormalizedTransaction]
    errors: list[PullError] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class NormalizeResult(_Frozen):
    """Outcome of a normalize step. Only ``ok`` carries a batch."""

    status: Literal["ok", "unrecognized", "invalid"]
    batch: NormalizedBatch | None = None
    dialect: str | None = None
    message: str | None = None
