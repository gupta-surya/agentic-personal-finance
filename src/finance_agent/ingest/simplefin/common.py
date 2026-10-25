"""Parsing shared by both SimpleFIN dialects: transactions and accounts.

SimpleFIN already uses our sign convention (debits negative, credits positive),
so amounts pass through unchanged.
"""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from finance_agent.ingest.contract import (
    Money,
    NormalizedAccount,
    NormalizedTransaction,
)


class RawTransaction(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    posted: int  # epoch seconds; 0 while pending
    amount: Money
    description: str
    transacted_at: int | None = None
    pending: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)


class RawAccount(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    id: str
    name: str
    currency: str
    balance: Money
    available_balance: Money | None = Field(default=None, alias="available-balance")
    balance_date: int | None = Field(default=None, alias="balance-date")
    transactions: list[RawTransaction] = Field(default_factory=list)
    conn_id: str | None = None  # v2
    org: dict[str, Any] | None = None  # v1


def _reject_constant(name: str) -> object:
    raise ValueError(f"{name} is not valid JSON")


def load_json(body: bytes) -> object:
    """Decode and parse; JSON numbers become Decimal so their text survives."""
    return json.loads(body.decode("utf-8"), parse_float=Decimal, parse_constant=_reject_constant)


def dumps_exact(value: object) -> str:
    """JSON-encode ``value``, writing Decimal as the exact number text it was parsed from."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return "{" + ",".join(f"{json.dumps(k)}:{dumps_exact(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(dumps_exact(v) for v in value) + "]"
    return json.dumps(value)


def local_date(epoch: int | None, tz: ZoneInfo) -> date | None:
    """The calendar date of ``epoch`` in the user's timezone; 0 and None mean "unknown"."""
    if not epoch:
        return None
    return datetime.fromtimestamp(epoch, tz=tz).date()


def currency_kind(currency: str) -> str:
    # A custom currency is identified by a URL. We never fetch it (no web access).
    return "custom" if currency.lower().startswith(("http://", "https://")) else "iso"


def normalize_account(
    raw_account: dict[str, Any], connection_key: str, tz: ZoneInfo
) -> tuple[NormalizedAccount, list[NormalizedTransaction]]:
    """Validate one raw account object and convert it and its transactions."""
    account = RawAccount.model_validate(raw_account)
    kind = currency_kind(account.currency)
    normalized = NormalizedAccount(
        connection_key=connection_key,
        external_id=account.id,
        name=account.name,
        currency=account.currency,
        currency_kind="custom" if kind == "custom" else "iso",
        balance=account.balance,
        available_balance=account.available_balance,
        balance_as_of=(
            datetime.fromtimestamp(account.balance_date, tz=UTC)
            if account.balance_date is not None
            else None
        ),
    )
    raw_transactions: list[dict[str, Any]] = raw_account.get("transactions", [])
    transactions = []
    for txn, raw_txn in zip(account.transactions, raw_transactions, strict=True):
        hint = txn.extra.get("category")
        transactions.append(
            NormalizedTransaction(
                connection_key=connection_key,
                account_external_id=account.id,
                external_id=txn.id,
                amount=txn.amount,
                description=txn.description,
                posted_date=local_date(txn.posted, tz),
                transacted_date=local_date(txn.transacted_at, tz),
                pending=txn.pending,
                category_hint=hint if isinstance(hint, str) else None,
                raw=dumps_exact(raw_txn),
            )
        )
    return normalized, transactions


def describe_validation_error(error: ValidationError) -> str:
    """Field paths and reasons only. Never the offending values, which may be financial data."""
    parts = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors()[:10]]
    return "; ".join(parts)
