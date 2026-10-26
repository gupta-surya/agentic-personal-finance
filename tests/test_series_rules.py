from datetime import date
from decimal import Decimal

import pytest

from finance_agent.queries.series_rules import catalog_params, share, top_groups

SPEND: dict[str | None, Decimal] = {
    "rent": Decimal("1500.00"),
    "groceries": Decimal("366.20"),
    "dining": Decimal("94.50"),
    "transport": Decimal("94.50"),
    None: Decimal("94.50"),
}


def test_top_groups_ranks_by_spend_then_name_with_uncategorized_last() -> None:
    assert top_groups(SPEND, 2) == {"rent", "groceries"}
    # three groups tie at 94.50: dining < transport < uncategorized
    assert top_groups(SPEND, 3) == {"rent", "groceries", "dining"}
    assert top_groups(SPEND, 4) == {"rent", "groceries", "dining", "transport"}


def test_top_groups_with_n_at_or_above_the_group_count_keeps_everyone() -> None:
    assert top_groups(SPEND, 5) == set(SPEND)
    assert top_groups(SPEND, 50) == set(SPEND)


@pytest.mark.parametrize("n", [0, -1])
def test_top_groups_needs_at_least_one(n: int) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        top_groups(SPEND, n)


@pytest.mark.parametrize(
    ("amount", "total", "expected"),
    [
        ("1", "3", "0.3333"),
        ("2", "3", "0.6667"),
        ("1", "20000", "0.0000"),  # 0.00005 is a tie: rounds to the even digit
        ("3", "20000", "0.0002"),  # 0.00015 is a tie: rounds to the even digit
        ("-25", "100", "-0.2500"),  # a refund can make a share negative
        ("150", "100", "1.5000"),  # ...or exceed 1
        ("5", "0", "0"),  # a zero total never divides
    ],
)
def test_share_rounds_to_four_places_half_even(amount: str, total: str, expected: str) -> None:
    assert share(Decimal(amount), Decimal(total)) == Decimal(expected)


def test_params_echo_the_arguments_and_omit_none_extras() -> None:
    params = catalog_params(
        date(2026, 3, 1), date(2026, 4, 1), "USD", top_n=None, group_by="category", measure="spend"
    )

    assert params == {
        "start": "2026-03-01",
        "end": "2026-04-01",
        "currency": "USD",
        "group_by": "category",
        "measure": "spend",
    }
