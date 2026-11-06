from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from finance_agent.queries.result import MonthlyCategorySpendRow, SpendBreakdownRow


def test_folded_bucket_cannot_name_a_category() -> None:
    with pytest.raises(ValidationError, match="no category"):
        MonthlyCategorySpendRow(
            month=date(2026, 3, 1), category="groceries", spend=Decimal("1"), is_other=True
        )
    with pytest.raises(ValidationError, match="no group"):
        SpendBreakdownRow(group="rent", amount=Decimal("1"), share=Decimal("1"), is_other=True)


def test_a_real_category_named_other_is_not_the_folded_bucket() -> None:
    real = MonthlyCategorySpendRow(month=date(2026, 3, 1), category="other", spend=Decimal("5"))
    folded = MonthlyCategorySpendRow(
        month=date(2026, 3, 1), category=None, spend=Decimal("5"), is_other=True
    )
    assert real.is_other is False
    assert folded.is_other is True


def test_breakdown_money_rejects_floats() -> None:
    with pytest.raises(ValidationError):
        SpendBreakdownRow(group="rent", amount=1.5, share=Decimal("1"))
    with pytest.raises(ValidationError):
        SpendBreakdownRow(group="rent", amount=Decimal("1"), share=0.5)
