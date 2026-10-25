"""The envelope every catalog query returns.

Charts and the verifier both consume this shape: the frontend renders ``rows`` or
``value``, and the verifier traces each number in a response back to a
``result_id`` from the same turn.

Money is ``Decimal`` and serializes to JSON as a string, so no precision is lost
between Postgres and the browser. Floats are rejected on the way in.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Generic, Self, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, JsonValue, model_validator


def _reject_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("money must be a Decimal or decimal string, never a float")
    return value


Money = Annotated[Decimal, BeforeValidator(_reject_float)]

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
    value: Money | None = None
    rows: list[RowT] | None = None

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


class CashFlowRow(BaseModel):
    """Money in and out for one calendar month. ``net = inflow - outflow``."""

    model_config = ConfigDict(frozen=True)

    month: date  # first day of the month
    inflow: Money  # sum of credits, zero or more
    outflow: Money  # sum of debits as a positive number
    net: Money
