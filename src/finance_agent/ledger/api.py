"""``/api/transactions`` and ``/api/accounts``: row-level reads for the user's own browser.

Mounted only on a database-backed app (the synthetic catalog has no rows), and only behind
``local_guard.harden`` (Host, Origin and the per-launch session token). No model is involved.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import ValidationError

from finance_agent.charts.period import Period, PeriodError, PeriodPreset, resolve_period
from finance_agent.db.loader import Connection
from finance_agent.ledger import reads
from finance_agent.ledger.models import (
    AccountList,
    AccountPeriodSummary,
    Sort,
    Status,
    TransactionDetail,
    TransactionPage,
)
from finance_agent.queries.pg_catalog import PostgresSeriesCatalog

ConnectionSession = Callable[[], AbstractContextManager[Connection]]


def ledger_router(
    read_session: ConnectionSession, tenant_id: str, today: Callable[[], date]
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/transactions")
    def transactions(
        start: date | None = None,
        end: date | None = None,
        account_id: Annotated[list[int] | None, Query()] = None,
        category: Annotated[list[str] | None, Query()] = None,
        q: str | None = None,
        min_amount: Decimal | None = None,
        max_amount: Decimal | None = None,
        status: Annotated[list[Status] | None, Query()] = None,
        include_transfers: bool = True,
        sort: Sort = "date_desc",
        limit: Annotated[int, Query(ge=1, le=reads.MAX_LIMIT)] = 100,
        cursor: str | None = None,
        currency: str = "USD",
    ) -> TransactionPage:
        filters = reads.TransactionFilters(
            start=start,
            end=end,
            account_ids=account_id or [],
            categories=category or [],
            q=q,
            min_amount=min_amount,
            max_amount=max_amount,
            statuses=status or [],
            include_transfers=include_transfers,
            currency=currency,
        )
        try:
            with read_session() as conn:
                return reads.list_transactions(conn, tenant_id, filters, sort, limit, cursor)
        except ValueError as err:  # a malformed cursor
            raise HTTPException(422, str(err)) from None

    @router.get("/transactions/{txn_id}")
    def transaction(txn_id: int) -> TransactionDetail:
        try:
            with read_session() as conn:
                return reads.get_transaction(conn, tenant_id, txn_id, today())
        except LookupError:
            raise HTTPException(404, "no such transaction") from None

    @router.get("/accounts")
    def accounts(currency: str = "USD") -> AccountList:
        with read_session() as conn:
            return reads.list_accounts(conn, tenant_id, today(), currency)

    @router.get("/accounts/{account_id}/summary")
    def account_summary(
        account_id: int,
        preset: PeriodPreset = PeriodPreset.LAST_3_MONTHS,
        start: date | None = None,
        end: date | None = None,
    ) -> AccountPeriodSummary:
        try:
            period = Period(preset=preset, start=start, end=end)
            with read_session() as conn:
                earliest = PostgresSeriesCatalog(conn, tenant_id).earliest_date

                resolved = resolve_period(period, today(), earliest)
                return reads.account_summary(
                    conn, tenant_id, account_id, resolved.start, resolved.end
                )
        except LookupError:
            raise HTTPException(404, "no such account") from None
        except (ValidationError, PeriodError) as err:
            raise HTTPException(422, str(err)) from None

    return router
