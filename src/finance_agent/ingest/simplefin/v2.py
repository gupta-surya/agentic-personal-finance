"""SimpleFIN protocol v2: ``errlist``, a ``connections`` list, and ``conn_id`` on accounts."""

from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from finance_agent.ingest.contract import (
    NormalizedAccount,
    NormalizedBatch,
    NormalizedConnection,
    NormalizedTransaction,
    PullError,
)
from finance_agent.ingest.simplefin.common import normalize_account


class RawConnection(BaseModel):
    model_config = ConfigDict(frozen=True)

    conn_id: str
    name: str
    org_id: str | None = None
    org_url: str | None = None
    sfin_url: str | None = None


class RawError(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    msg: str
    conn_id: str | None = None
    account_id: str | None = None


def normalize_v2(doc: dict[str, Any], tz: ZoneInfo, warnings: list[str]) -> NormalizedBatch:
    connections = {
        c.conn_id: NormalizedConnection(
            provider_key=c.conn_id,
            name=c.name,
            org_id=c.org_id,
            org_url=c.org_url,
            sfin_url=c.sfin_url,
        )
        for c in (RawConnection.model_validate(c) for c in doc.get("connections", []))
    }

    accounts: list[NormalizedAccount] = []
    transactions: list[NormalizedTransaction] = []
    for raw_account in doc["accounts"]:
        conn_id = raw_account.get("conn_id")
        if conn_id not in connections:
            raise ValueError("v2 account has no conn_id matching a connection")
        account, account_transactions = normalize_account(raw_account, conn_id, tz)
        accounts.append(account)
        transactions.extend(account_transactions)

    errors = [
        PullError(
            code=e.code,
            message=e.msg,
            connection_key=e.conn_id,
            account_external_id=e.account_id,
        )
        for e in (RawError.model_validate(e) for e in doc.get("errlist", []))
    ]
    return NormalizedBatch(
        source="simplefin",
        dialect="v2",
        connections=list(connections.values()),
        accounts=accounts,
        transactions=transactions,
        errors=errors,
        warnings=warnings,
    )
