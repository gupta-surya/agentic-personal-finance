"""The envelope every catalog query returns.

Charts and the verifier both consume this shape: the frontend renders ``rows`` or
``value``, and the verifier traces each number in a response back to a
``result_id`` from the same turn.

Money is ``Decimal`` and serializes to JSON as a string, so no precision is lost
between Postgres and the browser. Floats are rejected on the way in.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Generic, Self, TypeVar

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)


def _reject_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("money must be a Decimal or decimal string, never a float")
    return value


Money = Annotated[Decimal, BeforeValidator(_reject_float)]

# What every money-valued query says about its own signs, so a reader (or a model)
# can't misread them. Implementations put this in ``QueryResult.amounts_in``.
AMOUNTS_IN_DECIMAL = (
    "Decimal amounts as strings, in the currency named in params. "
    "Spend is a positive magnitude; refunds net against it."
)


def _first_of_month(value: date) -> date:
    if value.day != 1:
        raise ValueError(f"month must be the first day of a month, got {value.isoformat()}")
    return value


RowT = TypeVar("RowT", bound=BaseModel)


class QueryResult(BaseModel, Generic[RowT]):  # noqa: UP046 - pydantic generics need TypeVar here
    """One query execution: what was asked, and either a single value or rows.

    Exactly one of ``value`` and ``rows`` is set. An empty ``rows`` list means
    "no data", which is different from a scalar ``value`` of zero.
    """

    model_config = ConfigDict(frozen=True)

    query: str  # catalog name, e.g. "monthly_spend_by_category"
    params: dict[str, JsonValue]  # the arguments used, JSON-encoded (dates as ISO strings)
    result_id: str  # unique per execution; the verifier cites this
    data_version: str  # opaque; changes whenever the underlying data may have changed
    as_of: datetime  # when the underlying data was last synced (timezone-aware)
    amounts_in: str  # units and sign conventions, in words (see AMOUNTS_IN_DECIMAL)
    value: Money | None = None
    rows: list[RowT] | None = None
    totals: dict[str, Money] = Field(default_factory=dict)  # named column totals, if any

    @field_validator("as_of")
    @classmethod
    def _as_of_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _exactly_one_payload(self) -> Self:
        if (self.value is None) == (self.rows is None):
            raise ValueError("exactly one of value and rows must be set")
        return self


class MonthlyCategorySpendRow(BaseModel):
    """Net spend for one category in one calendar month.

    Spend is positive money out (``-SUM(amount)``), so refunds reduce it.
    """

    model_config = ConfigDict(frozen=True)

    month: date  # first day of the month
    category: str | None  # None = uncategorized
    spend: Money

    _month_is_first = field_validator("month")(_first_of_month)


class CashFlowRow(BaseModel):
    """Money in and out for one calendar month. ``net = inflow - outflow``."""

    model_config = ConfigDict(frozen=True)

    month: date  # first day of the month
    inflow: Money  # sum of credits, zero or more
    outflow: Money  # sum of debits as a positive number
    net: Money

    _month_is_first = field_validator("month")(_first_of_month)

    @model_validator(mode="after")
    def _net_matches(self) -> Self:
        if self.net != self.inflow - self.outflow:
            raise ValueError(
                f"net must equal inflow - outflow ({self.inflow} - {self.outflow}), got {self.net}"
            )
        return self
