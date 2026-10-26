"""Classify one transaction for flow reporting. Pure, no database.

Order matters. A transfer is checked first, so a miscategorized transfer can never be
spend or income. Then income (by the category's flag, never by its name), then the sign.
"""

from decimal import Decimal
from enum import StrEnum


class Kind(StrEnum):
    TRANSFER = "transfer"
    INCOME = "income"
    EXPENSE = "expense"
    CREDIT = "credit"  # a refund or reimbursement: money in against a categorized expense
    UNCATEGORIZED_INFLOW = "uncategorized_inflow"


def classify(
    amount: Decimal,
    *,
    is_internal_transfer: bool,
    category: str | None,
    category_is_income: bool,
) -> Kind:
    """Transfer, then income, then expense (negative), then credit or uncategorized inflow.

    A zero amount is an expense of nothing, so it never adds to inflow.
    """
    if is_internal_transfer:
        return Kind.TRANSFER
    if category is not None and category_is_income:
        return Kind.INCOME
    if amount <= 0:
        return Kind.EXPENSE
    if category is not None:
        return Kind.CREDIT
    return Kind.UNCATEGORIZED_INFLOW
