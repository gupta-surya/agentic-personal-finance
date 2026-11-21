import re
from datetime import date, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from finance_agent.charts.period import (
    Period,
    PeriodError,
    PeriodPreset,
    ResolvedPeriod,
    comparison_label,
    previous_of,
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


# (preset, today, previous start, previous exclusive end, comparison label)
PREVIOUS = [
    ("this_month", date(2026, 10, 25), date(2026, 9, 1), date(2026, 9, 26), "vs Sep 1–25"),
    ("this_month", date(2026, 1, 10), date(2025, 12, 1), date(2025, 12, 11), "vs Dec 1–10"),
    ("this_month", date(2026, 3, 31), date(2026, 2, 1), date(2026, 3, 1), "vs Feb 2026"),
    ("this_month", date(2024, 3, 31), date(2024, 2, 1), date(2024, 3, 1), "vs Feb 2024"),
    ("this_month", date(2026, 10, 1), date(2026, 9, 1), date(2026, 9, 2), "vs Sep 1–1"),
    ("this_month", date(2026, 5, 31), date(2026, 4, 1), date(2026, 5, 1), "vs Apr 2026"),
    ("last_month", date(2026, 10, 25), date(2026, 8, 1), date(2026, 9, 1), "vs Aug 2026"),
    ("last_month", date(2026, 1, 5), date(2025, 11, 1), date(2025, 12, 1), "vs Nov 2025"),
    (
        "last_3_months",
        date(2026, 10, 25),
        date(2026, 4, 1),
        date(2026, 7, 1),
        "vs Apr 2026 – Jun 2026",
    ),
    (
        "last_6_months",
        date(2026, 10, 25),
        date(2025, 10, 1),
        date(2026, 4, 1),
        "vs Oct 2025 – Mar 2026",
    ),
    (
        "last_12_months",
        date(2026, 10, 25),
        date(2024, 10, 1),
        date(2025, 10, 1),
        "vs Oct 2024 – Sep 2025",
    ),
    (
        "year_to_date",
        date(2026, 10, 25),
        date(2025, 1, 1),
        date(2025, 10, 26),
        "vs Jan 1, 2025 – Oct 25, 2025",
    ),
    (
        "year_to_date",
        date(2024, 2, 29),
        date(2023, 1, 1),
        date(2023, 3, 1),
        "vs Jan 2023 – Feb 2023",
    ),
    ("last_year", date(2026, 10, 25), date(2024, 1, 1), date(2025, 1, 1), "vs Jan 2024 – Dec 2024"),
]


@pytest.mark.parametrize(("preset", "today", "start", "end", "label"), PREVIOUS)
def test_previous_period_is_calendar_aligned(
    preset: str, today: date, start: date, end: date, label: str
) -> None:
    previous = previous_of(resolve(preset, today))

    assert previous is not None
    assert (previous.start, previous.end) == (start, end)
    assert comparison_label(previous) == label


def test_all_time_has_no_previous_period() -> None:
    period = resolve_period(
        Period(preset=PeriodPreset.ALL_TIME), date(2026, 10, 25), lambda: date(2024, 1, 1)
    )

    assert previous_of(period) is None


def test_custom_previous_is_the_equal_length_window_before() -> None:
    custom = resolve_period(
        Period(preset=PeriodPreset.CUSTOM, start=date(2026, 3, 1), end=date(2026, 4, 1)),
        date(2026, 10, 25),
    )
    previous = previous_of(custom)

    assert previous is not None
    assert (previous.start, previous.end) == (date(2026, 1, 29), date(2026, 3, 1))
    assert comparison_label(previous) == "vs previous 31 days"


def test_month_aligned_presets_abut_and_start_on_the_first() -> None:
    month_aligned = ("last_month", "last_3_months", "last_6_months", "last_12_months", "last_year")
    day = date(2023, 1, 1)
    while day < date(2028, 1, 1):  # exhaustive over every day of five years, leap included
        for preset in month_aligned:
            current = resolve(preset, day)
            previous = previous_of(current)
            assert previous is not None
            assert previous.end == current.start
            assert previous.start.day == 1
        day += timedelta(1)
