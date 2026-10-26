from datetime import date
from decimal import Decimal

import pytest

from finance_agent.charts.templates.common import (
    category_label,
    format_money,
    format_share,
    month_label,
    span_label,
)


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        ("3200.00", "USD", "$3,200.00"),
        ("-210.75", "USD", "−$210.75"),
        ("1234567.5", "USD", "$1,234,567.50"),
        ("0.07", "USD", "$0.07"),
        ("12", "EUR", "€12.00"),
        ("-0.00", "USD", "$0.00"),
        ("0.123", "USD", "$0.123"),
        ("5.00", "CHF", "CHF 5.00"),
    ],
)
def test_format_money_keeps_every_digit(amount: str, currency: str, expected: str) -> None:
    assert format_money(Decimal(amount), currency) == expected


@pytest.mark.parametrize(
    ("share", "expected"),
    [
        ("0.7377", "73.77%"),
        ("0.0098", "0.98%"),
        ("1.0000", "100%"),
        ("0", "0%"),
        ("-0.05", "−5%"),
        ("1.25", "125%"),
        ("0.12345", "12.345%"),
    ],
)
def test_format_share_moves_the_decimal_point_only(share: str, expected: str) -> None:
    assert format_share(Decimal(share)) == expected


def test_labels() -> None:
    assert category_label("fees_interest") == "Fees interest"
    assert category_label("other") == "Other"
    assert category_label(None) == "Uncategorized"
    assert category_label(None, is_other=True) == "Everything else"


def test_month_and_span_labels() -> None:
    assert month_label(date(2026, 3, 1)) == "Mar 2026"
    assert span_label(date(2026, 3, 1), date(2026, 3, 1)) == "Mar 2026"
    assert span_label(date(2026, 4, 1), date(2026, 9, 1)) == "Apr 2026 – Sep 2026"
