"""SimpleFIN protocol v1: ``errors`` strings, and an ``org`` object on every account."""

from typing import Any
from zoneinfo import ZoneInfo

from finance_agent.ingest.contract import (
    NormalizedAccount,
    NormalizedBatch,
    NormalizedConnection,
    NormalizedTransaction,
    PullError,
)
from finance_agent.ingest.simplefin.common import normalize_account


def _connection_from_org(org: dict[str, Any]) -> NormalizedConnection:
    """The spec prefers ``domain`` as the globally unique institution id, then ``id``."""

    def text(key: str) -> str | None:
        value = org.get(key)
        return value if isinstance(value, str) and value else None

    key = text("domain") or text("id") or text("sfin-url")
    if key is None:
        raise ValueError("account org has none of domain, id or sfin-url")
    return NormalizedConnection(
        provider_key=key,
        name=text("name") or text("domain") or key,
        org_id=text("id"),
        org_url=text("url"),
        sfin_url=text("sfin-url"),
    )


def normalize_v1(doc: dict[str, Any], tz: ZoneInfo, warnings: list[str]) -> NormalizedBatch:
    connections: dict[str, NormalizedConnection] = {}
    accounts: list[NormalizedAccount] = []
    transactions: list[NormalizedTransaction] = []

    for raw_account in doc["accounts"]:
        org = raw_account.get("org")
        if not isinstance(org, dict):
            raise ValueError("v1 account has no org object")
        connection = _connection_from_org(org)
        connections.setdefault(connection.provider_key, connection)
        account, account_transactions = normalize_account(raw_account, connection.provider_key, tz)
        accounts.append(account)
        transactions.extend(account_transactions)

    errors = [PullError(code="legacy", message=str(m)) for m in doc.get("errors", [])]
    return NormalizedBatch(
        source="simplefin",
        dialect="v1",
        connections=list(connections.values()),
        accounts=accounts,
        transactions=transactions,
        errors=errors,
        warnings=warnings,
    )
