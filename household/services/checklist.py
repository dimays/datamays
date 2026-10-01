"""Checklists and the Today summary, built from one set of rows.

Both screens sort the same open occurrences into the same buckets, so they
can never disagree about what is overdue. Everything is computed from one
load — two queries for any number of chores (see `load()`) — plus whatever
`occurrences.refresh()` has to write for a chore whose next date arrived.
"""

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Q

from .. import scheduling
from ..dates import household_today
from ..models import Chore, Occurrence, OccurrenceStatus
from . import occurrences, permissions
from .members import display_name, partner_of

UPCOMING_DAYS = 7

# In display order. "Due now" covers an occurrence whose due date has come
# but whose deadline hasn't — it is not late yet, but it is not future either.
BUCKETS = [
    ("overdue", "Overdue"),
    ("today", "Today"),
    ("upcoming", f"Next {UPCOMING_DAYS} days"),
    ("later", "Later"),
    ("whenever", "Whenever"),
]
BUCKET_ORDER = {key: index for index, (key, _) in enumerate(BUCKETS)}


@dataclass
class Row:
    """One open occurrence, with everything a template needs to draw it."""

    occurrence: Occurrence
    chore: Chore
    bucket: str
    days_overdue: int
    can_manage: bool
    needs_confirmation: bool

    @property
    def assignee_name(self):
        return display_name(self.chore.assignee)

    @property
    def schedule_words(self):
        return self.chore.describe_schedule()


def bucket_for(occurrence, today):
    if occurrence.due_on is None:
        return "whenever"
    if occurrence.is_overdue(today):
        return "overdue"
    if occurrence.due_on <= today:
        return "today"
    if occurrence.due_on <= today + timedelta(days=UPCOMING_DAYS):
        return "upcoming"
    return "later"


def load(today):
    """Every active chore with an open occurrence, collapse applied."""
    chores = occurrences.with_open_occurrence(
        Chore.objects.filter(is_active=True).select_related("owner", "assignee")
    )
    occurrences.refresh(chores, today)
    return [chore for chore in chores if chore.open_occurrences]


def rows_for(user, chores, today):
    rows = []
    for chore in chores:
        occurrence = chore.open_occurrences[0]
        rows.append(
            Row(
                occurrence=occurrence,
                chore=chore,
                bucket=bucket_for(occurrence, today),
                days_overdue=occurrence.days_overdue(today),
                can_manage=permissions.can_manage(user, chore),
                needs_confirmation=permissions.needs_confirmation(user, chore),
            )
        )

    # Most overdue first; then soonest; undated last; ties by title.
    rows.sort(
        key=lambda row: (
            BUCKET_ORDER[row.bucket],
            -row.days_overdue,
            row.occurrence.due_on or today,
            row.chore.title.casefold(),
        )
    )
    return rows


def grouped(rows):
    """Rows as [(key, label, rows)] for the non-empty buckets, in order."""
    return [
        (key, label, [row for row in rows if row.bucket == key])
        for key, label in BUCKETS
        if any(row.bucket == key for row in rows)
    ]


def _split(user, chores):
    partner = partner_of(user)
    mine = [chore for chore in chores if chore.assignee_id == user.pk]
    shared = [chore for chore in chores if chore.assignee_id is None]
    theirs = [chore for chore in chores if partner and chore.assignee_id == partner.pk]
    return partner, mine, shared, theirs


def checklist(user, *, include_partner, today=None):
    today = today or household_today()
    partner, mine, shared, theirs = _split(user, load(today))

    return {
        "today": today,
        "partner": partner,
        "partner_name": display_name(partner) if partner else None,
        "mine": grouped(rows_for(user, mine, today)),
        "shared": grouped(rows_for(user, shared, today)),
        "theirs": grouped(rows_for(user, theirs, today)) if include_partner else None,
    }


def today_summary(user, *, include_partner, today=None):
    """What the Today screen shows, top to bottom.

    Yours and the household's shared chores, with the other person's overdue
    and due-today chores alongside when the toggle is on. "Coming up" is only
    the easy-to-forget kind — see `scheduling.is_low_frequency()`.
    """
    today = today or household_today()
    partner, mine, shared, theirs = _split(user, load(today))
    rows = rows_for(user, mine + shared, today)
    partner_rows = rows_for(user, theirs, today) if include_partner else []

    return {
        "today": today,
        "partner_name": display_name(partner) if partner else None,
        "overdue": [row for row in rows if row.bucket == "overdue"],
        "due_today": [row for row in rows if row.bucket == "today"],
        "coming_up": [
            row
            for row in rows
            if row.bucket == "upcoming" and scheduling.is_low_frequency(row.chore.schedule)
        ],
        "partner_rows": [row for row in partner_rows if row.bucket in ("overdue", "today")],
    }


def overdue_count(user, today=None):
    """For the nav badge: one query, on every page.

    Cheap on purpose, so it skips the collapse — a fixed chore whose next
    date has arrived but nobody has refreshed still counts as overdue here.
    The hourly sweep keeps that window short, and opening the checklist
    closes it.
    """
    today = today or household_today()
    return (
        Occurrence.objects.filter(status=OccurrenceStatus.OPEN, chore__is_active=True)
        .filter(Q(chore__assignee=user) | Q(chore__assignee__isnull=True))
        .filter(Q(deadline__lt=today) | Q(deadline__isnull=True, due_on__lt=today))
        .count()
    )
