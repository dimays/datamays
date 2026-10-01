"""Maintenance: the upkeep overview, the cost log, and the starter library."""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Prefetch

from .. import scheduling
from ..dates import household_today, to_household_date
from ..maintenance_library import BY_KEY, LIBRARY
from ..models import Chore, MaintenanceArea, MaintenanceItem, Occurrence, OccurrenceStatus
from . import occurrences
from .checklist import bucket_for

DUE_SOON_DAYS = 30


def items_with_state(today=None):
    """Every maintenance item with its chore, open occurrence, and last done.

    Three queries for any number of items: the items with their chores, the
    open occurrences, and the most recent completions.
    """
    today = today or household_today()
    items = list(
        MaintenanceItem.objects.select_related("chore", "chore__assignee")
        .annotate(occurrence_count=Count("chore__occurrences"))
        .prefetch_related(
            Prefetch(
                "chore__occurrences",
                queryset=Occurrence.objects.filter(status=OccurrenceStatus.OPEN),
                to_attr="open_occurrences",
            )
        )
    )
    occurrences.refresh([item.chore for item in items], today)

    last_done = {}
    for occurrence in (
        Occurrence.objects.filter(chore__maintenance_item__isnull=False, status=OccurrenceStatus.DONE)
        .select_related("completed_by")
        .order_by("chore_id", "-completed_at")
    ):
        last_done.setdefault(occurrence.chore_id, occurrence)

    for item in items:
        chore = item.chore
        item.current = chore.open_occurrences[0] if chore.open_occurrences else None
        item.bucket = bucket_for(item.current, today) if item.current else None
        item.last_done = last_done.get(chore.pk)
    return items


def overview(today=None):
    """What the Upkeep page shows: what needs attention, then everything by area."""
    today = today or household_today()
    items = items_with_state(today)
    horizon = today + timedelta(days=DUE_SOON_DAYS)

    needs_attention = sorted(
        (
            item
            for item in items
            if item.chore.is_active
            and item.current
            and item.current.due_on
            and (item.bucket == "overdue" or item.current.due_on <= horizon)
        ),
        # Overdue first, most overdue first; then by when each is due.
        key=lambda item: (item.bucket != "overdue", item.current.due_on),
    )

    by_area = defaultdict(list)
    for item in items:
        by_area[item.area].append(item)

    return {
        "today": today,
        "needs_attention": needs_attention,
        "areas": [
            (label, sorted(by_area[key], key=lambda item: item.chore.title.casefold()))
            for key, label in MaintenanceArea.choices
            if by_area.get(key)
        ],
        "count": len(items),
    }


def cost_by_year(item):
    """{year: total logged cost}, newest first — "what has this cost us"."""
    totals = defaultdict(Decimal)
    for occurrence in item.chore.occurrences.filter(status=OccurrenceStatus.DONE, cost__isnull=False):
        totals[to_household_date(occurrence.completed_at).year] += occurrence.cost
    return sorted(totals.items(), reverse=True)


# --- the starter library ---------------------------------------------------


def _next_month_day(month, day, today):
    candidate = scheduling.clamp_to_month(today.year, month, day)
    if candidate < today:
        candidate = scheduling.clamp_to_month(today.year + 1, month, day)
    return candidate


def _starts_on(entry, today):
    """The soonest date in the entry's cycle from today.

    "Every six months from April 30" adopted in September starts on October
    30, not next April: every month the cycle visits is a candidate.
    """
    if not entry.month_day:
        return today

    month, day = entry.month_day
    step = entry.interval if entry.frequency == scheduling.Frequency.MONTHLY else 12
    months = {scheduling.shift_month(2000, month, step * k)[1] for k in range(max(1, 12 // step))}
    return min(_next_month_day(candidate, day, today) for candidate in months)


def available_library_entries():
    """Starter entries not yet adopted, matched by title."""
    taken = set(
        MaintenanceItem.objects.values_list("chore__title", flat=True)
    )
    return [entry for entry in LIBRARY if entry.title not in taken]


@transaction.atomic
def adopt(key, today=None):
    """Turn a starter entry into a real maintenance item on the schedule."""
    today = today or household_today()
    entry = BY_KEY[key]

    starts_on = _starts_on(entry, today)
    chore = Chore.objects.create(
        title=entry.title,
        owner=None,
        assignee=None,
        frequency=entry.frequency,
        interval=entry.interval,
        anchor=entry.anchor,
        starts_on=starts_on,
        deadline_offset_days=entry.deadline_offset_days,
    )
    item = MaintenanceItem.objects.create(
        chore=chore,
        area=entry.area,
        instructions=entry.instructions,
        supplies=entry.supplies,
        estimated_cost=entry.estimated_cost,
    )
    occurrences.reschedule(chore, today=today)
    return item

