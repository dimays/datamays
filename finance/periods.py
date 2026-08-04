"""Budget period arithmetic.

Budgets are anchored rather than fixed to the calendar, because household
budgets rarely line up with calendar months — a grocery budget that resets on
payday is more useful than one that resets on the 1st. An anchor date defines
both the phase (which weekday, which day of the month) and the origin, and
every period is derived from it.

Pure date arithmetic, no database access, so the edge cases — month lengths,
leap days, dates before the anchor — are cheap to test exhaustively.
"""

import calendar
from datetime import date, timedelta

DAYS_PER_WEEK = 7


def _clamp_to_month(year: int, month: int, day: int) -> date:
    """Anchor day 31 lands on the 28th, 29th, or 30th in shorter months."""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = (year * 12 + (month - 1)) + delta
    return index // 12, index % 12 + 1


def weekly_period(anchor: date, on_date: date) -> tuple[date, date]:
    # Floor division keeps this correct for dates before the anchor.
    weeks = (on_date - anchor).days // DAYS_PER_WEEK
    start = anchor + timedelta(days=weeks * DAYS_PER_WEEK)
    return start, start + timedelta(days=DAYS_PER_WEEK - 1)


def monthly_period(anchor: date, on_date: date) -> tuple[date, date]:
    start = _clamp_to_month(on_date.year, on_date.month, anchor.day)

    if on_date < start:
        year, month = _shift_month(on_date.year, on_date.month, -1)
        start = _clamp_to_month(year, month, anchor.day)

    next_year, next_month = _shift_month(start.year, start.month, 1)
    next_start = _clamp_to_month(next_year, next_month, anchor.day)

    return start, next_start - timedelta(days=1)


def annual_period(anchor: date, on_date: date) -> tuple[date, date]:
    start = _clamp_to_month(on_date.year, anchor.month, anchor.day)

    if on_date < start:
        start = _clamp_to_month(on_date.year - 1, anchor.month, anchor.day)

    next_start = _clamp_to_month(start.year + 1, anchor.month, anchor.day)

    return start, next_start - timedelta(days=1)


PERIOD_FUNCTIONS = {
    "weekly": weekly_period,
    "monthly": monthly_period,
    "annual": annual_period,
}


def period_containing(period_type: str, anchor: date, on_date: date) -> tuple[date, date]:
    try:
        return PERIOD_FUNCTIONS[period_type](anchor, on_date)
    except KeyError:
        raise ValueError(f"Unknown budget period type: {period_type!r}") from None


def previous_period(period_type: str, anchor: date, start: date) -> tuple[date, date]:
    return period_containing(period_type, anchor, start - timedelta(days=1))


def next_period(period_type: str, anchor: date, end: date) -> tuple[date, date]:
    return period_containing(period_type, anchor, end + timedelta(days=1))


def elapsed_fraction(start: date, end: date, on_date: date) -> float:
    """How far through a period a date falls, from 0.0 to 1.0.

    Drives "you are 60% through the month and 85% through the budget", which is
    the number that actually tells you whether to make the purchase.
    """
    total_days = (end - start).days + 1

    if total_days <= 0:
        return 1.0

    elapsed_days = (on_date - start).days + 1

    return max(0.0, min(1.0, elapsed_days / total_days))


def quarter_bounds(year: int, quarter: int) -> tuple[date, date]:
    """The calendar quarter's first and last day. Always the calendar quarter —
    QFRs are not anchored like budgets, since "Q1" needs to mean the same thing
    to everyone comparing reports."""
    if quarter not in (1, 2, 3, 4):
        raise ValueError(f"Quarter must be 1-4, got {quarter!r}.")

    start_month = (quarter - 1) * 3 + 1
    end_month = start_month + 2

    start = date(year, start_month, 1)
    end = date(year, end_month, calendar.monthrange(year, end_month)[1])

    return start, end


def quarter_containing(on_date: date) -> tuple[int, int]:
    """(year, quarter) for the calendar quarter a date falls in."""
    return on_date.year, (on_date.month - 1) // 3 + 1


def previous_quarter(year: int, quarter: int) -> tuple[int, int]:
    return (year - 1, 4) if quarter == 1 else (year, quarter - 1)


def quarters_between(start_year: int, start_quarter: int, end_year: int, end_quarter: int):
    """Every (year, quarter) from start through end, inclusive, oldest first."""
    year, quarter = start_year, start_quarter

    while (year, quarter) <= (end_year, end_quarter):
        yield year, quarter
        year, quarter = (year + 1, 1) if quarter == 4 else (year, quarter + 1)
