"""How a chore repeats: pure date arithmetic, no database access.

A schedule is one of two kinds, and the difference matters more than any
other choice here:

- **Fixed** — driven by the calendar. "Every Monday", "the second Saturday
  of the month", "April 15 every year". Due dates exist whether or not
  anyone did the last one, so a fixed chore can be *missed*.
- **After completion** — driven by the work. "90 days after the filter was
  last changed". The clock only restarts when the job is done, so an
  after-completion chore is never missed; it just becomes overdue.

Deliberately not `dateutil.rrule`, which *skips* months lacking the requested
day: "monthly on the 31st" would silently not happen in February, April,
June, September, or November. A household means "the last day of the month",
so a day past a month's end is clamped to that month's last day, the same
rule `finance/periods.py` uses for budgets.

Everything here is a pure function over dates, so the edge cases — month-end
days, leap days, a fifth weekday in a four-weekday month, seasons that wrap
the new year — are cheap to test exhaustively (see tests/test_scheduling.py).
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from django.db import models

# Backstops against a schedule whose filters reject every candidate date.
# Validation should make that impossible; these keep a mistake from hanging a
# request — or, for a yearly schedule, from running past year 9999 and
# raising — if one ever gets through. A step cap alone isn't enough: 20,000
# yearly steps is further than the calendar goes.
MAX_STEPS = 20_000
HORIZON_YEARS = 100

# The longest gap a schedule may have, by unit — ten years in each. Plenty for
# a household, and well short of running off the end of the calendar.
MAX_INTERVAL = {"daily": 3650, "weekly": 520, "monthly": 120, "yearly": 10}

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
ORDINALS = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}


class Frequency(models.TextChoices):
    ONCE = "once", "Doesn't repeat"
    DAILY = "daily", "Daily"
    WEEKLY = "weekly", "Weekly"
    MONTHLY = "monthly", "Monthly"
    YEARLY = "yearly", "Yearly"


class MonthlyMode(models.TextChoices):
    DAY = "day", "On the same day of the month"
    NTH_WEEKDAY = "nth_weekday", "On the same weekday of the month (e.g. second Saturday)"
    LAST_WEEKDAY = "last_weekday", "On the last of that weekday (e.g. last Friday)"


class Anchor(models.TextChoices):
    FIXED = "fixed", "On a fixed schedule"
    AFTER_COMPLETION = "after_completion", "Counting from when it was last done"


@dataclass(frozen=True)
class Schedule:
    """Everything needed to work out due dates.

    `starts_on` does double duty, as it does in a calendar app: it is the
    first due date, and it sets the phase — which weekday a weekly chore
    falls on, which day of the month a monthly one does. For a one-off it is
    simply the due date, and may be None ("whenever").
    """

    frequency: str
    starts_on: date | None
    interval: int = 1
    weekdays: tuple = ()
    monthly_mode: str = MonthlyMode.DAY
    anchor: str = Anchor.FIXED
    ends_on: date | None = None
    max_occurrences: int | None = None
    deadline_offset_days: int | None = None
    season: tuple | None = None  # (start_month, end_month), inclusive, may wrap
    counts_from: date | None = None  # when the chore was created; see fixed_dates()

    @property
    def repeats(self):
        return self.frequency != Frequency.ONCE

    @property
    def is_fixed(self):
        return self.repeats and self.anchor == Anchor.FIXED


# --- calendar helpers ------------------------------------------------------


def clamp_to_month(year: int, month: int, day: int) -> date:
    """Day 31 lands on the 28th, 29th, or 30th in shorter months."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def add_months(value: date, months: int) -> date:
    year, month = shift_month(value.year, value.month, months)
    return clamp_to_month(year, month, value.day)


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date | None:
    """The nth `weekday` of a month, or None when the month has fewer."""
    first = date(year, month, 1)
    day = first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    return day if day.month == month else None


def last_weekday(year: int, month: int, weekday: int) -> date:
    last = date(year, month, calendar.monthrange(year, month)[1])
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def week_of_month(value: date) -> int:
    """1 for the first seven days, 2 for the next seven, and so on."""
    return (value.day - 1) // 7 + 1


def is_last_weekday_of_month(value: date) -> bool:
    return (value + timedelta(days=7)).month != value.month


def in_season(value: date, season) -> bool:
    if not season:
        return True

    start, end = season
    if start <= end:
        return start <= value.month <= end

    # A window that wraps the new year, such as November to February.
    return value.month >= start or value.month <= end


def start_of_season_on_or_after(value: date, season) -> date:
    """`value` if it is in season, otherwise the first day the season opens."""
    if in_season(value, season):
        return value

    start_month = season[0]
    year = value.year if value.month < start_month else value.year + 1
    return date(year, start_month, 1)


# --- fixed schedules -------------------------------------------------------


def _candidates(schedule: Schedule):
    """Every calendar-generated date from `starts_on` on, before filtering."""
    start = schedule.starts_on
    step = schedule.interval

    if schedule.frequency == Frequency.DAILY:
        day = start
        while True:
            yield day
            day += timedelta(days=step)

    elif schedule.frequency == Frequency.WEEKLY:
        weekdays = sorted(set(schedule.weekdays)) or [start.weekday()]
        week = start - timedelta(days=start.weekday())
        while True:
            for weekday in weekdays:
                day = week + timedelta(days=weekday)
                # The first week can include weekdays before the start date.
                if day >= start:
                    yield day
            week += timedelta(weeks=step)

    elif schedule.frequency == Frequency.MONTHLY:
        months = 0
        while True:
            year, month = shift_month(start.year, start.month, months)

            if schedule.monthly_mode == MonthlyMode.NTH_WEEKDAY:
                # A "fifth Tuesday" simply doesn't happen in a month with
                # four — the same thing a calendar app does.
                day = nth_weekday(year, month, start.weekday(), week_of_month(start))
            elif schedule.monthly_mode == MonthlyMode.LAST_WEEKDAY:
                day = last_weekday(year, month, start.weekday())
            else:
                day = clamp_to_month(year, month, start.day)

            if day is not None and day >= start:
                yield day
            months += step

    elif schedule.frequency == Frequency.YEARLY:
        years = 0
        while True:
            # February 29 falls on the 28th in common years.
            yield clamp_to_month(start.year + years, start.month, start.day)
            years += step


def fixed_dates(schedule: Schedule):
    """Every due date of a fixed schedule, in order, honoring its limits.

    The season filter runs before the occurrence count, so "10 times, April
    to October" means ten in-season dates, not ten dates of which some are
    silently dropped.
    """
    if not schedule.is_fixed or schedule.starts_on is None:
        return

    horizon = schedule.starts_on.year + HORIZON_YEARS
    produced = 0
    candidates = _candidates(schedule)
    for steps in range(MAX_STEPS):
        try:
            day = next(candidates)
        except (OverflowError, ValueError):
            # A date past year 9999. validate() caps intervals so this can't
            # come from the form; this keeps anything else from a 500.
            return
        if day.year > horizon:
            return
        if schedule.ends_on and day > schedule.ends_on:
            return
        if not in_season(day, schedule.season):
            continue

        yield day
        # Dates before the schedule was set are not occurrences of it, so
        # they don't use up its count: "ten times" means ten from when it was
        # set, not ten from a start date in the past.
        if schedule.counts_from and day < schedule.counts_from:
            continue
        produced += 1
        if schedule.max_occurrences and produced >= schedule.max_occurrences:
            return


def first_fixed_on_or_after(schedule: Schedule, day: date) -> date | None:
    return next((due for due in fixed_dates(schedule) if due >= day), None)


def next_fixed_after(schedule: Schedule, day: date) -> date | None:
    return next((due for due in fixed_dates(schedule) if due > day), None)


def arrived_since(schedule: Schedule, open_due: date, today: date) -> list:
    """Every due date after `open_due` that has arrived by `today`, in order."""
    arrived = []
    for due in fixed_dates(schedule):
        if due > today:
            break
        if due > open_due:
            arrived.append(due)
    return arrived


def superseding_due(schedule: Schedule, open_due: date, today: date) -> date | None:
    """The newest due date that has arrived since `open_due`, if any.

    A fixed chore keeps one open occurrence. When a later due date arrives
    while it is still open, the old one is missed and this newer one takes
    its place — only the newest, so a week away from a daily chore collapses
    into one row rather than a wall of seven.
    """
    arrived = arrived_since(schedule, open_due, today)
    return arrived[-1] if arrived else None


# --- after-completion schedules --------------------------------------------


def advance(schedule: Schedule, day: date) -> date:
    """`day` plus one interval in the schedule's unit."""
    if schedule.frequency == Frequency.DAILY:
        return day + timedelta(days=schedule.interval)
    if schedule.frequency == Frequency.WEEKLY:
        return day + timedelta(weeks=schedule.interval)
    if schedule.frequency == Frequency.MONTHLY:
        return add_months(day, schedule.interval)
    return add_months(day, 12 * schedule.interval)


def next_after_completion(schedule: Schedule, done_on: date, occurrences_so_far: int) -> date | None:
    """When an after-completion chore is next due, given when it was done.

    Outside its season, it waits for the season to open: a lawn job finished
    in October with a 90-day interval is next due in April, not January.
    """
    if schedule.max_occurrences and occurrences_so_far >= schedule.max_occurrences:
        return None

    try:
        due = advance(schedule, done_on)
    except (OverflowError, ValueError):
        return None
    if schedule.season:
        due = start_of_season_on_or_after(due, schedule.season)
    if schedule.ends_on and due > schedule.ends_on:
        return None
    return due


# --- the questions callers ask ---------------------------------------------


def first_due(schedule: Schedule, today: date) -> date | None:
    """The due date for a chore's first open occurrence, or None for none.

    A one-off is due when it says (None meaning "whenever"). A repeating
    chore created with a start date in the past begins at its next due date
    from today rather than arriving already overdue for dates before it
    existed.
    """
    if not schedule.repeats:
        return schedule.starts_on

    if schedule.anchor == Anchor.AFTER_COMPLETION:
        due = schedule.starts_on
        if schedule.season:
            due = start_of_season_on_or_after(due, schedule.season)
        if schedule.ends_on and due > schedule.ends_on:
            return None
        return due

    return first_fixed_on_or_after(schedule, max(today, schedule.starts_on))


def next_due(schedule: Schedule, *, previous_due, done_on: date, occurrences_so_far: int):
    """The due date after an occurrence is done or skipped, or None when finished."""
    if not schedule.repeats:
        return None

    if schedule.anchor == Anchor.AFTER_COMPLETION:
        return next_after_completion(schedule, done_on, occurrences_so_far)

    # Fixed: the calendar decides, whenever the work was actually done. Done
    # early, the next is the one after the date it was due; done late, the
    # caller collapses anything else that has since arrived.
    return next_fixed_after(schedule, previous_due or done_on)


def is_low_frequency(schedule: Schedule) -> bool:
    """Rare enough to need a heads-up before it is due.

    The Today screen lists these in "Coming up" a week ahead: one-offs and
    anything repeating a fortnight apart or more — the filter change, the
    registration renewal. Daily and weekly routines are left out; listing
    tomorrow's bins every day would drown the things that are easy to forget.
    """
    if not schedule.repeats:
        return True
    if schedule.frequency == Frequency.DAILY:
        return schedule.interval >= 14
    if schedule.frequency == Frequency.WEEKLY:
        return schedule.interval >= 2
    return True


def deadline_for(schedule: Schedule, due: date | None) -> date | None:
    if due is None or schedule.deadline_offset_days is None:
        return None
    try:
        return due + timedelta(days=schedule.deadline_offset_days)
    except OverflowError:  # past year 9999; no deadline rather than a 500
        return None


# --- words -----------------------------------------------------------------


def _every(schedule: Schedule, unit: str) -> str:
    if schedule.interval == 1:
        return {"day": "Daily", "week": "Weekly", "month": "Monthly", "year": "Yearly"}[unit]
    return f"Every {schedule.interval} {unit}s"


def _season_words(season) -> str:
    start, end = season
    return f"{calendar.month_abbr[start]}–{calendar.month_abbr[end]}"


def describe(schedule: Schedule) -> str:
    """A schedule in the words a person would use: "Every 2 weeks on Mon, Thu"."""
    if not schedule.repeats:
        return "Once"

    unit = {
        Frequency.DAILY: "day",
        Frequency.WEEKLY: "week",
        Frequency.MONTHLY: "month",
        Frequency.YEARLY: "year",
    }[schedule.frequency]

    if schedule.anchor == Anchor.AFTER_COMPLETION:
        count = schedule.interval
        words = f"{count} {unit}{'' if count == 1 else 's'} after it was last done"
    else:
        start = schedule.starts_on
        words = _every(schedule, unit)

        if schedule.frequency == Frequency.WEEKLY:
            weekdays = sorted(set(schedule.weekdays)) or [start.weekday()]
            words += " on " + ", ".join(WEEKDAY_NAMES[day] for day in weekdays)
        elif schedule.frequency == Frequency.MONTHLY:
            weekday = calendar.day_name[start.weekday()]
            if schedule.monthly_mode == MonthlyMode.NTH_WEEKDAY:
                words += f" on the {ORDINALS[week_of_month(start)]} {weekday}"
            elif schedule.monthly_mode == MonthlyMode.LAST_WEEKDAY:
                words += f" on the last {weekday}"
            else:
                words += f" on day {start.day}"
        elif schedule.frequency == Frequency.YEARLY:
            words += f" on {calendar.month_abbr[start.month]} {start.day}"

    if schedule.season:
        words += f", {_season_words(schedule.season)}"
    if schedule.max_occurrences:
        words += f", {schedule.max_occurrences} times"
    if schedule.ends_on:
        words += f", until {schedule.ends_on:%b} {schedule.ends_on.day}, {schedule.ends_on.year}"

    return words


# --- validation ------------------------------------------------------------


def reachable_months(schedule: Schedule) -> set:
    """The months a fixed schedule's dates can ever fall in."""
    if schedule.frequency in (Frequency.DAILY, Frequency.WEEKLY):
        return set(range(1, 13))
    if schedule.frequency == Frequency.YEARLY:
        return {schedule.starts_on.month}
    # Monthly every n: the months the cycle visits from the start month.
    return {
        shift_month(schedule.starts_on.year, schedule.starts_on.month, schedule.interval * step)[1]
        for step in range(12)
    }


def validate(schedule: Schedule) -> dict:
    """Problems with a schedule, as {field: message}. Empty means valid.

    Field names match the Chore model's, so `Chore.clean()` can raise these
    directly as a ValidationError.
    """
    errors = {}

    if not schedule.repeats:
        return errors

    if schedule.starts_on is None:
        errors["starts_on"] = "A repeating chore needs a first due date."
    if schedule.interval < 1:
        errors["interval"] = "Repeat at least every 1."
    elif schedule.interval > MAX_INTERVAL.get(schedule.frequency, schedule.interval):
        # Found in review: "every 9000 years" passed validation and then ran
        # off the end of the calendar.
        errors["interval"] = f"That's longer than this app can schedule — at most every {MAX_INTERVAL[schedule.frequency]}."
    if any(day not in range(7) for day in schedule.weekdays):
        errors["weekdays"] = "Weekdays run from Monday (0) to Sunday (6)."
    if schedule.weekdays and schedule.frequency != Frequency.WEEKLY:
        errors["weekdays"] = "Weekdays only apply to a weekly schedule."
    if schedule.anchor == Anchor.AFTER_COMPLETION and schedule.weekdays:
        errors["weekdays"] = (
            "Counting from when it was last done has no fixed weekday — "
            "clear the weekdays, or switch to a fixed schedule."
        )
    if schedule.season is not None:
        start, end = schedule.season
        if start not in range(1, 13) or end not in range(1, 13):
            errors["season_start_month"] = "Pick a start and an end month."
    if (
        schedule.is_fixed
        and schedule.starts_on
        and schedule.season
        and not any(in_season(date(2000, month, 1), schedule.season) for month in reachable_months(schedule))
    ):
        errors["season_start_month"] = (
            "This schedule never falls inside that season — its due dates are "
            "always in other months."
        )
    if (
        schedule.is_fixed
        and schedule.frequency == Frequency.MONTHLY
        and schedule.monthly_mode == MonthlyMode.LAST_WEEKDAY
        and schedule.starts_on
        and not is_last_weekday_of_month(schedule.starts_on)
    ):
        weekday = calendar.day_name[schedule.starts_on.weekday()]
        errors["starts_on"] = (
            f"{schedule.starts_on:%b} {schedule.starts_on.day} isn't the last {weekday} of "
            f"{schedule.starts_on:%B} — pick the last {weekday} as the first due date."
        )
    if schedule.ends_on and schedule.starts_on and schedule.ends_on < schedule.starts_on:
        errors["ends_on"] = "The end date is before the first due date."
    if schedule.max_occurrences is not None and schedule.max_occurrences < 1:
        errors["max_occurrences"] = "Repeat at least once."
    if schedule.deadline_offset_days is not None and schedule.deadline_offset_days < 0:
        errors["deadline_offset_days"] = "A deadline can't come before the due date."

    return errors
