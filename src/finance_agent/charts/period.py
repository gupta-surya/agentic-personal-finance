"""Period presets resolved to explicit dates against one ``today`` per turn.

The planner picks a preset from an enum and never does date math; the resolver turns
it into ``[start, end)`` (``end`` exclusive, matching ``SeriesCatalog``), so the
verifier knows exactly which range a number covers. Nothing here reads the clock.

Semantics:
- ``this_month`` and ``year_to_date`` end the day after ``today`` (no future data).
- ``last_N_months`` is N *complete* calendar months before the current month; the
  current partial month is excluded.
- ``last_year`` is the previous complete calendar year.
- ``all_time`` runs from the earliest data date (injected) through ``today``.
- ``custom`` uses the caller's dates as given: ``start`` inclusive, ``end`` exclusive.
"""

from collections.abc import Callable
from datetime import date, timedelta
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class PeriodError(ValueError):
    """The period cannot be resolved; the API maps this to HTTP 422."""


class PeriodPreset(StrEnum):
    THIS_MONTH = "this_month"
    LAST_MONTH = "last_month"
    LAST_3_MONTHS = "last_3_months"
    LAST_6_MONTHS = "last_6_months"
    LAST_12_MONTHS = "last_12_months"
    YEAR_TO_DATE = "year_to_date"
    LAST_YEAR = "last_year"
    ALL_TIME = "all_time"
    CUSTOM = "custom"


_LAST_N_MONTHS = {
    PeriodPreset.LAST_MONTH: 1,
    PeriodPreset.LAST_3_MONTHS: 3,
    PeriodPreset.LAST_6_MONTHS: 6,
    PeriodPreset.LAST_12_MONTHS: 12,
}


class Period(BaseModel):
    """What the planner fills. ``start``/``end`` are allowed only for ``custom``."""

    model_config = ConfigDict(frozen=True)

    preset: PeriodPreset
    start: date | None = None
    end: date | None = None  # exclusive

    @model_validator(mode="after")
    def _dates_only_for_custom(self) -> Self:
        if self.preset is PeriodPreset.CUSTOM:
            if self.start is None or self.end is None:
                raise ValueError("custom period requires start and end")
            if self.start >= self.end:
                raise ValueError("custom period requires start < end")
        elif self.start is not None or self.end is not None:
            raise ValueError("start and end are only allowed with preset 'custom'")
        return self


class ResolvedPeriod(BaseModel):
    """Explicit dates, echoed in the chart spec so the covered range is visible."""

    model_config = ConfigDict(frozen=True)

    preset: PeriodPreset
    start: date  # inclusive
    end: date  # exclusive
    label: str  # e.g. "Apr 1, 2026 – Sep 30, 2026"


def _add_months(first_of_month: date, months: int) -> date:
    index = first_of_month.year * 12 + (first_of_month.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def _fmt(day: date) -> str:
    return f"{_MONTHS[day.month - 1]} {day.day}, {day.year}"


def _resolved(preset: PeriodPreset, start: date, end: date) -> ResolvedPeriod:
    label = f"{_fmt(start)} – {_fmt(end - timedelta(days=1))}"
    return ResolvedPeriod(preset=preset, start=start, end=end, label=label)


def resolve_period(
    period: Period,
    today: date,
    earliest: Callable[[], date | None] | None = None,
) -> ResolvedPeriod:
    """Resolve ``period`` against ``today``.

    ``earliest`` returns the first date with data (``None`` if there is none); it is
    required only for ``all_time``. An empty history resolves to ``[today, today+1)``.
    """
    preset = period.preset
    tomorrow = today + timedelta(days=1)
    this_month = today.replace(day=1)

    if preset is PeriodPreset.CUSTOM:
        assert period.start is not None and period.end is not None  # enforced by Period
        return _resolved(preset, period.start, period.end)
    if preset is PeriodPreset.THIS_MONTH:
        return _resolved(preset, this_month, tomorrow)
    if preset in _LAST_N_MONTHS:
        return _resolved(preset, _add_months(this_month, -_LAST_N_MONTHS[preset]), this_month)
    if preset is PeriodPreset.YEAR_TO_DATE:
        return _resolved(preset, date(today.year, 1, 1), tomorrow)
    if preset is PeriodPreset.LAST_YEAR:
        return _resolved(preset, date(today.year - 1, 1, 1), date(today.year, 1, 1))
    if earliest is None:
        raise PeriodError("all_time needs an earliest-date source")
    first = earliest()
    return _resolved(preset, first if first is not None and first <= today else today, tomorrow)
