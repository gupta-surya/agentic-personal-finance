"""Deterministic groundedness: every figure in the narration must trace to the chart's data.

No model runs here (DESIGN principle 3). The chart spec's numeric values *are* the query
results for this turn; a monetary amount or percentage in the prose that is not one of them
(within display rounding) is untraceable and blocks the response. Incidental integers — small
counts like "last 3 months" or "top 8", and 4-digit years — are not financial claims and are
ignored. Percentages are reconciled against fractions, since shares are stored as fractions
(0.7061 -> "70.61%"). The deterministic title is grounded by construction, so its figures are
trusted too.
"""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from finance_agent.charts.spec import ChartSpec

# $1,234.56 | 1234.56 | 1,234 | 45% | -$12.00
_TOKEN = re.compile(r"-?\$?\d[\d,]*(?:\.\d+)?%?")
_ROUNDINGS = (4, 2, 1, 0)


@dataclass(frozen=True)
class VerifyReport:
    ok: bool
    unmatched: list[str]  # financial tokens in the prose that trace to nothing
    checked: list[str]  # tokens treated as financial claims


def _to_decimal(token: str) -> Decimal | None:
    cleaned = token.replace("$", "").replace(",", "").rstrip("%")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _is_financial_claim(token: str) -> bool:
    if "$" in token or "%" in token or "." in token:
        return True
    digits = token.lstrip("-").replace(",", "")
    if len(digits) == 4 and digits.isdigit() and 1900 <= int(digits) <= 2099:
        return False  # a year, not a figure
    value = _to_decimal(token)
    return value is not None and abs(value) >= 100  # a bare small integer is incidental


def _rounds_to(value: Decimal, candidate: Decimal) -> bool:
    return any(value == candidate.quantize(Decimal(1).scaleb(-dp)) for dp in _ROUNDINGS)


def ground_truth(spec: ChartSpec) -> set[Decimal]:
    """Every number a grounded sentence may cite: the series/annotation values, plus the
    figures in the deterministic title."""
    values: set[Decimal] = set()
    for series in spec.series:
        for point in series.points:
            for component in (point.y, point.low, point.high):
                if component is not None:
                    values.add(Decimal(str(component)))
    for annotation in spec.annotations:
        if annotation.y is not None:
            values.add(Decimal(str(annotation.y)))
    for token in _TOKEN.findall(spec.title):
        parsed = _to_decimal(token)
        if parsed is not None:
            values.add(parsed)
    return values


def _matches(value: Decimal, is_percent: bool, truth: set[Decimal]) -> bool:
    for base in truth:
        if _rounds_to(value, base):
            return True
        if is_percent and _rounds_to(value, base * 100):  # share stored as a fraction
            return True
    return False


def verify(prose: str, spec: ChartSpec | None) -> VerifyReport:
    truth = ground_truth(spec) if spec is not None else set()
    checked: list[str] = []
    unmatched: list[str] = []
    for token in _TOKEN.findall(prose):
        if not _is_financial_claim(token):
            continue
        checked.append(token)
        value = _to_decimal(token)
        if value is None or not _matches(value, token.endswith("%"), truth):
            unmatched.append(token)
    return VerifyReport(ok=not unmatched, unmatched=unmatched, checked=checked)
