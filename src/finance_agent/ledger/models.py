"""Response shapes for the ledger API. Money is a Decimal (a string in JSON), signed the way the
schema stores it: debits negative, credits positive. Nothing here reaches a model."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from finance_agent.queries.result import Money

Role = Literal["on_budget", "credit", "loan", "investment"]
Status = Literal["needs_review", "pending", "transfer", "hidden"]
Sort = Literal["date_desc", "date_asc", "amount_desc", "amount_asc"]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True)


class AccountRef(_Model):
    id: int
    name: str
    mask: str | None  # the schema has no mask column yet; always null for now
    role: Role
    institution: str


class OtherLeg(_Model):
    id: int
    account_name: str
    posted_date: date | None


class TransferInfo(_Model):
    group_id: int
    kind: Literal["internal", "card_payment"]
    confidence: Literal["high", "low"]
    other_leg: OtherLeg | None


class TransactionRow(_Model):
    id: int
    posted_date: date | None
    transacted_date: date | None
    pending: bool
    merchant: str
    description: str
    amount: Money
    currency: str
    category: str | None
    category_source: Literal["rule", "model", "user"] | None
    suggested_category: str | None  # TASK-04c; null until it exists
    needs_review: bool
    note: str | None
    hidden: bool
    account: AccountRef
    transfer: TransferInfo | None


class TransactionTotals(_Model):
    """Same row filter as the catalog (posted, no internal transfers, no hidden rows, cash and
    credit accounts, one currency), so these equal Home's Spent and Income for the same window."""

    count: int
    money_out: Money
    money_in: Money
    transfers_excluded: int
    currency: str
    result_id: str


class TransactionPage(_Model):
    rows: list[TransactionRow]
    next_cursor: str | None
    totals: TransactionTotals


class MonthAmount(_Model):
    month: date
    amount: Money


class MerchantHistory(_Model):
    visits_12m: int
    total_12m: Money
    monthly: list[MonthAmount]
    result_id: str


class TransactionDetail(_Model):
    transaction: TransactionRow
    merchant_history: MerchantHistory | None


class AccountRow(_Model):
    id: int
    name: str
    display_name: str | None
    mask: str | None
    institution: str
    role: Role
    role_source: Literal["rule", "user"]
    currency: str
    balance: Money
    available_balance: Money | None
    balance_as_of: datetime | None
    stale: bool
    closed: bool
    hidden: bool
    last_sync_at: datetime | None
    source: str
    month_spend: Money


class AccountGroup(_Model):
    role: Role
    label: str
    accounts: list[AccountRow]
    total: Money


class AccountsSummary(_Model):
    cash: Money
    credit_owed: Money
    cash_after_cards: Money
    net_worth: Money
    currency: str
    result_id: str


class AccountList(_Model):
    groups: list[AccountGroup]
    summary: AccountsSummary


class BalancePoint(_Model):
    as_of: datetime
    balance: Money


class CardPayment(_Model):
    id: int
    posted_date: date | None
    amount: Money
    other_account_name: str


class AccountPeriodSummary(_Model):
    account_id: int
    start: date
    end: date
    balance_history: list[BalancePoint]
    transaction_count: int
    needs_review_count: int
    last_card_payment: CardPayment | None
    result_id: str
