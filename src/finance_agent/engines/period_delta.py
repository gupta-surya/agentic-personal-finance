"""Change between two scalar results of the same query over consecutive periods."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from finance_agent.queries.result import Money, QueryResult, ScalarRow, Share


class DeltaRow(BaseModel):
    """``amount = current - previous``; ``percent = amount / |previous|`` as a Decimal
    fraction rounded to four places (``0.1234`` is 12.34%), or ``None`` when the previous
    value is zero (a change from nothing has no percentage, never infinity)."""

    model_config = ConfigDict(frozen=True)

    amount: Money
    percent: Share | None


def period_delta(
    current: QueryResult[ScalarRow], previous: QueryResult[ScalarRow]
) -> QueryResult[DeltaRow]:
    """Compare two scalar results. The result id names both sources, so the figure is
    traceable to the two queries it came from."""
    if current.value is None or previous.value is None:
        raise ValueError("period_delta needs two scalar results")
    # Subtracting different queries or currencies would give a number that means nothing.
    if current.query != previous.query:
        raise ValueError(
            f"period_delta needs one query, got {current.query!r} and {previous.query!r}"
        )
    if current.amounts_in != previous.amounts_in:
        raise ValueError("period_delta needs both results in the same units")
    if current.params.get("currency") != previous.params.get("currency"):
        raise ValueError("period_delta needs both results in the same currency")
    amount = current.value - previous.value
    percent = (
        (amount / abs(previous.value)).quantize(Decimal("0.0001")) if previous.value != 0 else None
    )
    same_version = current.data_version == previous.data_version
    return QueryResult[DeltaRow](
        query="period_delta",
        params={
            "current_result_id": current.result_id,
            "previous_result_id": previous.result_id,
            "source_query": current.query,
        },
        result_id=f"period_delta:{current.result_id}:{previous.result_id}",
        data_version=(
            current.data_version
            if same_version
            else f"{current.data_version}+{previous.data_version}"
        ),
        as_of=max(current.as_of, previous.as_of),
        amounts_in=current.amounts_in,
        rows=[DeltaRow(amount=amount, percent=percent)],
    )
