"""The occurrence lifecycle: what happens when a chore is done, skipped, or
left alone.

The rules, all in one place:

- A chore has **at most one open occurrence** (a database constraint backs
  this up). Completing or skipping it opens the next, in the same
  transaction.
- A **fixed** chore's open occurrence is *missed* when the next due date
  arrives, and the newest arrived date opens in its place. Only the newest —
  a week away from a daily chore is one overdue item, not seven. This
  happens even if the old one's deadline has not passed yet: the next one
  has arrived, and two open copies of the same chore help nobody.
- An **after-completion** chore is never missed; it just becomes overdue.
  Its clock restarts on the household date it was done or skipped.
- A **one-off** has one occurrence. Done is done.

Screens never depend on the hourly sweep having run: `refresh()` applies the
same collapse on read, in bulk, and only writes when something is actually
stale. A skipped scheduler run cannot show a stale chore.

Everything takes `today` explicitly (defaulting to `household_today()`) so
tests can pin the date rather than patch the clock.
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone

from .. import scheduling
from ..dates import household_today, to_household_date
from ..models import Chore, Occurrence, OccurrenceStatus

CLOSED_BY_A_PERSON = (OccurrenceStatus.DONE, OccurrenceStatus.SKIPPED)


def with_open_occurrence(chores):
    """Chores with their open occurrence prefetched as `open_occurrences`.

    One extra query for the whole set, which is what keeps a checklist's
    query count flat however many chores are on it.
    """
    return chores.prefetch_related(
        Prefetch(
            "occurrences",
            queryset=Occurrence.objects.filter(status=OccurrenceStatus.OPEN),
            to_attr="open_occurrences",
        )
    )


def _open(chore, due_on):
    if chore.repeats:
        deadline = scheduling.deadline_for(chore.schedule, due_on)
    else:
        deadline = chore.deadline

    return Occurrence.objects.create(chore=chore, due_on=due_on, deadline=deadline)


def _due_for_a_fresh_start(chore, today, *, starts_on_changed=False):
    schedule = chore.schedule

    if schedule.anchor == scheduling.Anchor.AFTER_COMPLETION:
        # A due date set by hand is what the person wants next.
        if starts_on_changed:
            return scheduling.first_due(schedule, today)
        # Otherwise rescheduling must not forget when the job was last done:
        # the furnace filter is still due 90 days after it was changed.
        last = (
            chore.occurrences.filter(status__in=CLOSED_BY_A_PERSON, completed_at__isnull=False)
            .order_by("-completed_at")
            .first()
        )
        if last is not None:
            return scheduling.next_after_completion(
                schedule, to_household_date(last.completed_at), chore.occurrences.count()
            )
        return scheduling.first_due(schedule, today)

    # A fixed schedule starts from today — but never on or before a date
    # already closed. Found in review: editing (or pausing and resuming) a
    # chore done today reopened today's occurrence, as if undone.
    last_closed = (
        chore.occurrences.exclude(status=OccurrenceStatus.OPEN)
        .exclude(due_on__isnull=True)
        .order_by("-due_on")
        .values_list("due_on", flat=True)
        .first()
    )
    start = today if last_closed is None else max(today, last_closed + timedelta(days=1))
    return scheduling.first_fixed_on_or_after(schedule, max(start, schedule.starts_on))


@transaction.atomic
def reschedule(chore, today=None, *, starts_on_changed=False):
    """Bring a chore's open occurrence in line with its schedule.

    Call it after creating a chore, and after editing one *only if the
    schedule changed* — replacing the open occurrence resets it, so an
    overdue chore that merely had its title edited would lose its place.

    Returns the open occurrence, or None when there is nothing to do.
    """
    today = today or household_today()
    current = chore.occurrences.select_for_update().filter(status=OccurrenceStatus.OPEN).first()

    if not chore.repeats:
        if current is not None:
            current.due_on = chore.starts_on
            current.deadline = chore.deadline
            current.save(update_fields=["due_on", "deadline", "updated_at"])
            return current
        if not chore.is_active:
            return None
        # A one-off already done for this date stays done. Anything else —
        # a new date for it, or a repeating chore just converted to a
        # one-off — is something to do, so it opens.
        latest = chore.occurrences.order_by("-pk").first()
        if latest is not None and latest.due_on == chore.starts_on:
            return None
        return _open(chore, chore.starts_on)

    if current is not None:
        current.delete()

    # Pausing a repeating chore takes it off every checklist; resuming it
    # starts afresh from today.
    if not chore.is_active:
        return None

    due = _due_for_a_fresh_start(chore, today, starts_on_changed=starts_on_changed)
    return _open(chore, due) if due is not None else None


def edit_signature(chore):
    """Everything about a chore that decides its open occurrence.

    Includes a one-off's deadline, which `Schedule` doesn't carry — found in
    review: changing only that left the open occurrence on the old date.
    """
    return (chore.schedule, chore.is_active, chore.deadline)


@transaction.atomic
def apply_edit(chore, before, today=None):
    """After a chore is saved from a form: bring its occurrence in line,
    but only if something that decides it changed.

    `before` is the stored chore as it was (re-read from the database before
    the form ran). Editing only a title or notes must not reschedule — it
    would reset an overdue chore. A schedule change restarts any occurrence
    limit from today (`schedule_set_on`).
    """
    today = today or household_today()
    if edit_signature(before) == edit_signature(chore):
        return None

    if before.schedule != chore.schedule:
        chore.schedule_set_on = today
        chore.save(update_fields=["schedule_set_on", "updated_at"])

    return reschedule(chore, today, starts_on_changed=before.starts_on != chore.starts_on)


def _advance(closed, today):
    """Open whatever comes after `closed`, or nothing if the series is over."""
    chore = closed.chore
    if not chore.is_active:
        return None

    schedule = chore.schedule
    due = scheduling.next_due(
        schedule,
        previous_due=closed.due_on,
        done_on=to_household_date(closed.completed_at),
        occurrences_so_far=chore.occurrences.count(),
    )
    if due is None:
        return None

    # Done very late, the next due date may itself be long gone.
    if schedule.is_fixed:
        due = scheduling.superseding_due(schedule, due, today) or due

    return _open(chore, due)


def _close(occurrence, status, *, by, note, now, today, cost=None):
    with transaction.atomic():
        # Locked and re-read, so a double tap closes it once and opens one
        # next occurrence, not two.
        locked = Occurrence.objects.select_for_update().select_related("chore").get(pk=occurrence.pk)
        if not locked.is_open:
            return None

        locked.status = status
        locked.completed_by = by
        locked.completed_at = now or timezone.now()
        locked.note = note
        locked.cost = cost
        locked.save(update_fields=["status", "completed_by", "completed_at", "note", "cost", "updated_at"])

        return _advance(locked, today or household_today())


def complete(occurrence, *, by, note="", cost=None, now=None, today=None):
    """Mark it done by `by` — who may not be the assignee — and open the next.

    `cost`, when given, is what doing it cost (maintenance, mostly), as a
    positive Decimal. Returns the next open occurrence, or None if the series
    is finished or this occurrence was no longer open.
    """
    return _close(occurrence, OccurrenceStatus.DONE, by=by, note=note, now=now, today=today, cost=cost)


def skip(occurrence, *, by, note="", now=None, today=None):
    """Deliberately not doing this one. For an after-completion chore the
    clock restarts from the skip, as if the decision were the work."""
    return _close(occurrence, OccurrenceStatus.SKIPPED, by=by, note=note, now=now, today=today)


@transaction.atomic
def reopen(occurrence):
    """Undo a done or skipped occurrence, for the accidental tap.

    Only the most recent: if anything has happened since other than the
    untouched next occurrence this one opened, the history stands and this
    returns False.
    """
    locked = Occurrence.objects.select_for_update().get(pk=occurrence.pk)
    if locked.status not in CLOSED_BY_A_PERSON:
        return False

    # Locked too: a concurrent completion of the next occurrence must either
    # finish first (and so block the undo) or wait for it.
    later = list(Occurrence.objects.select_for_update().filter(chore_id=locked.chore_id, pk__gt=locked.pk))
    if any(not item.is_open for item in later):
        return False

    for item in later:
        item.delete()

    locked.status = OccurrenceStatus.OPEN
    locked.completed_by = None
    locked.completed_at = None
    locked.cost = None
    locked.transaction = None
    locked.save(update_fields=["status", "completed_by", "completed_at", "cost", "transaction", "updated_at"])
    return True


def refresh(chores, today=None):
    """Apply the missed-occurrence collapse to chores already loaded.

    Expects `with_open_occurrence()` to have run, and updates each chore's
    `open_occurrences` in place so the caller can render straight from it.
    Writes only for a fixed chore whose next due date has arrived.
    """
    today = today or household_today()

    for chore in chores:
        current = chore.open_occurrences[0] if chore.open_occurrences else None
        if current is None or current.due_on is None or not chore.is_active:
            continue
        if not chore.schedule.is_fixed:
            continue

        newer = scheduling.superseding_due(chore.schedule, current.due_on, today)
        if newer is None:
            continue

        with transaction.atomic():
            # Conditional, so a concurrent completion is never overwritten.
            missed = Occurrence.objects.filter(pk=current.pk, status=OccurrenceStatus.OPEN).update(
                status=OccurrenceStatus.MISSED, updated_at=timezone.now()
            )
            if missed:
                chore.open_occurrences = [_open(chore, newer)]

    return chores


def sweep(today=None):
    """The scheduled half of `refresh()`: every active repeating fixed chore.

    Keeps the history honest for chores nobody has looked at, so a missed
    week is recorded as missed on the day it happened rather than whenever
    someone next opens the app.
    """
    chores = with_open_occurrence(
        Chore.objects.filter(is_active=True, anchor=scheduling.Anchor.FIXED).exclude(
            frequency=scheduling.Frequency.ONCE
        )
    )
    before = {chore.pk: chore.open_occurrences[:] for chore in chores}
    refresh(chores, today)
    return sum(1 for chore in chores if chore.open_occurrences != before[chore.pk])
