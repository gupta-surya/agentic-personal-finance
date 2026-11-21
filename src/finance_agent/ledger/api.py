"""``/api/transactions`` and ``/api/accounts``: row-level reads for the user's own browser.

Mounted only on a database-backed app (the synthetic catalog has no rows), and only behind
``local_guard.harden`` (Host, Origin and the per-launch session token). No model is involved.
"""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from finance_agent.charts.period import Period, PeriodError, PeriodPreset, resolve_period
from finance_agent.db.loader import Connection
from finance_agent.ledger import reads, writes
from finance_agent.ledger.models import (
    AccountList,
    AccountPeriodSummary,
    Role,
    Sort,
    Status,
    TransactionDetail,
    TransactionPage,
)
from finance_agent.queries.pg_catalog import PostgresSeriesCatalog

ConnectionSession = Callable[[], AbstractContextManager[Connection]]


class TransactionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str | None = None
    note: str | None = None  # null or "" clears it
    hidden: bool | None = None


class BulkEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[int] = Field(min_length=1, max_length=writes.MAX_BULK)
    category: str | None = None
    hidden: bool | None = None


class RuleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    merchant: str = Field(min_length=1, max_length=200)
    category: str
    apply_to_existing: bool = False


class TransferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["not_transfer", "link"]
    other_id: int | None = None


class AccountPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role | None = None
    display_name: str | None = Field(default=None, max_length=100)
    hidden: bool | None = None


class Updated(BaseModel):
    updated: int


class RuleResult(BaseModel):
    count: int  # rows the rule changed (or would change, for a preview)
    preview: bool


def ledger_router(
    read_session: ConnectionSession,
    tenant_id: str,
    today: Callable[[], date],
    write_session: ConnectionSession | None = None,
) -> APIRouter:
    """``write_session`` is a separate connection, so the read endpoints can stay read-only."""
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

    if write_session is not None:
        _write_routes(router, write_session, tenant_id, today)
    return router


def _write_routes(
    router: APIRouter, write_session: ConnectionSession, tenant_id: str, today: Callable[[], date]
) -> None:
    @contextmanager
    def failures() -> Iterator[None]:
        """Map action errors to statuses: unknown ids are 404, refused choices are 422."""
        try:
            yield
        except LookupError as err:
            raise HTTPException(404, str(err)) from None
        except ValueError as err:
            raise HTTPException(422, str(err)) from None

    @router.patch("/transactions/{txn_id}")
    def patch_transaction(txn_id: int, body: TransactionPatch) -> TransactionDetail:
        if not body.model_fields_set:
            raise HTTPException(422, "nothing to change")
        note = body.note if "note" in body.model_fields_set else "unset"
        with failures(), write_session() as conn:
            writes.edit_transaction(conn, tenant_id, txn_id, body.category, note, body.hidden)
            return reads.get_transaction(conn, tenant_id, txn_id, today())

    @router.post("/transactions/{txn_id}/accept-suggestion")
    def accept_suggestion(txn_id: int) -> None:
        raise HTTPException(409, "Suggestions are not available yet (TASK-04c).")

    @router.post("/transactions/bulk")
    def bulk(body: BulkEdit) -> Updated:
        with failures(), write_session() as conn:
            return Updated(
                updated=writes.bulk_edit(conn, tenant_id, body.ids, body.category, body.hidden)
            )

    @router.post("/transactions/{txn_id}/transfer")
    def transfer(txn_id: int, body: TransferRequest) -> TransactionDetail:
        with failures(), write_session() as conn:
            writes.change_transfer(conn, tenant_id, txn_id, body.action, body.other_id)
            return reads.get_transaction(conn, tenant_id, txn_id, today())

    @router.post("/rules")
    def rules(body: RuleRequest, preview: bool = False) -> RuleResult:
        with failures(), write_session() as conn:
            count = writes.save_rule(
                conn,
                tenant_id,
                body.merchant,
                body.category,
                apply_to_existing=body.apply_to_existing,
                dry_run=preview,
            )
            return RuleResult(count=count, preview=preview)

    @router.patch("/accounts/{account_id}")
    def patch_account(account_id: int, body: AccountPatch) -> AccountList:
        if not body.model_fields_set:
            raise HTTPException(422, "nothing to change")
        name = body.display_name if "display_name" in body.model_fields_set else "unset"
        with failures(), write_session() as conn:
            writes.edit_account(conn, tenant_id, account_id, body.role, name, body.hidden)
            return reads.list_accounts(conn, tenant_id, today())
