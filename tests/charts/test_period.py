import re
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from finance_agent.charts.period import (
    Period,
    PeriodError,
    PeriodPreset,
    ResolvedPeriod,
    resolve_period,
)


def resolve(preset: str, today: date) -> ResolvedPeriod:
    return resolve_period(Period(preset=PeriodPreset(preset)), today)


# (preset, today, expected start, expected exclusive end)
CASES = [
    ("this_month", date(2026, 10, 25), date(2026, 10, 1), date(2026, 10, 26)),
    ("this_month", date(2026, 1, 1), date(2026, 1, 1), date(2026, 1, 2)),
    ("last_month", date(2026, 10, 25), date(2026, 9, 1), date(2026, 10, 1)),
    ("last_month", date(2026, 1, 1), date(2025, 12, 1), date(2026, 1, 1)),
    ("last_3_months", date(2026, 10, 25), date(2026, 7, 1), date(2026, 10, 1)),
    ("last_3_months", date(2026, 1, 15), date(2025, 10, 1), date(2026, 1, 1)),
    ("last_6_months", date(2026, 10, 25), date(2026, 4, 1), date(2026, 10, 1)),
    ("last_6_months", date(2026, 3, 31), date(2025, 9, 1), date(2026, 3, 1)),
    ("last_12_months", date(2026, 10, 25), date(2025, 10, 1), date(2026, 10, 1)),
    ("last_12_months", date(2024, 2, 29), date(2023, 2, 1), date(2024, 2, 1)),
    ("year_to_date", date(2026, 10, 25), date(2026, 1, 1), date(2026, 10, 26)),
    ("year_to_date", date(2024, 2, 29), date(2024, 1, 1), date(2024, 3, 1)),
    ("year_to_date", date(2026, 12, 31), date(2026, 1, 1), date(2027, 1, 1)),
    ("last_year", date(2026, 10, 25), date(2025, 1, 1), date(2026, 1, 1)),
    ("last_year", date(2026, 1, 1), date(2025, 1, 1), date(2026, 1, 1)),
]


@pytest.mark.parametrize(("preset", "today", "start", "end"), CASES)
def test_preset_resolves(preset: str, today: date, start: date, end: date) -> None:
    resolved = resolve(preset, today)
    assert (resolved.start, resolved.end) == (start, end)
    assert resolved.preset == PeriodPreset(preset)


def test_label_names_inclusive_range() -> None:
    assert resolve("last_month", date(2026, 10, 25)).label == "Sep 1, 2026 – Sep 30, 2026"


def test_custom_passes_dates_through() -> None:
    period = Period(preset=PeriodPreset.CUSTOM, start=date(2026, 2, 1), end=date(2026, 4, 1))
    resolved = resolve_period(period, date(2026, 10, 25))
    assert (resolved.start, resolved.end) == (date(2026, 2, 1), date(2026, 4, 1))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"preset": "custom"},
        {"preset": "custom", "start": date(2026, 2, 1)},
        {"preset": "custom", "start": date(2026, 4, 1), "end": date(2026, 4, 1)},
        {"preset": "custom", "start": date(2026, 5, 1), "end": date(2026, 4, 1)},
        {"preset": "last_month", "start": date(2026, 2, 1)},
        {"preset": "this_month", "end": date(2026, 2, 1)},
    ],
)
def test_invalid_combinations_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Period.model_validate(kwargs)


def test_unknown_preset_rejected() -> None:
    with pytest.raises(ValidationError):
        Period.model_validate({"preset": "last_decade"})


def test_all_time_uses_injected_earliest() -> None:
    resolved = resolve_period(
        Period(preset=PeriodPreset.ALL_TIME), date(2026, 10, 25), lambda: date(2024, 6, 3)
    )
    assert (resolved.start, resolved.end) == (date(2024, 6, 3), date(2026, 10, 26))


def test_all_time_with_no_history_is_empty_not_error() -> None:
    resolved = resolve_period(
        Period(preset=PeriodPreset.ALL_TIME), date(2026, 10, 25), lambda: None
    )
    assert (resolved.start, resolved.end) == (date(2026, 10, 25), date(2026, 10, 26))


def test_all_time_without_source_raises() -> None:
    with pytest.raises(PeriodError):
        resolve_period(Period(preset=PeriodPreset.ALL_TIME), date(2026, 10, 25))


def test_charts_package_never_reads_the_clock() -> None:
    root = Path(__file__).parents[2] / "src" / "finance_agent" / "charts"
    pattern = re.compile(r"date\.today\(|datetime\.now\(|datetime\.utcnow\(|time\.time\(")
    offenders = [p.name for p in root.rglob("*.py") if pattern.search(p.read_text())]
    assert offenders == []
    assert list(root.rglob("*.py"))  # the grep is looking at real files
