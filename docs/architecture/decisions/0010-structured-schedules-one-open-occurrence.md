# 0010 — Structured schedules, one open occurrence per chore

**Status:** accepted
**Reverse cost:** medium — occurrence history is stored in this shape

## Context

Chores and home maintenance repeat, "similar to Google Calendar, but
simpler". Three questions follow:

1. How is a repeat rule stored?
2. Are future occurrences stored ahead of time, or computed?
3. What happens to a repeating chore nobody did?

## Decision

**Structured fields, not RRULE strings.** Frequency, interval, weekdays,
monthly mode, anchor, end date, count, season, and deadline offset are
ordinary columns. They validate field by field, render as an ordinary form,
and cover what a household needs. The arithmetic is our own pure functions
(`household/scheduling.py`), not `dateutil.rrule`, because rrule skips months
lacking the requested day — "monthly on the 31st" would not happen in five
months a year — where a household means "the last day".

**Two anchors.** *Fixed* schedules follow the calendar. *After-completion*
schedules count from when the job was last done — the right model for
filters, deep cleans, and anything where the interval matters more than the
date.

**One open occurrence per chore, materialized one at a time.** The current
occurrence is a row; the next is created when it is closed. Nothing is
generated ahead. A partial unique index enforces the "one".

**Missed occurrences collapse.** When a fixed chore's next due date arrives
while the current one is open, the current one is marked *missed* and only
the newest arrived date opens. After-completion chores are never missed —
they are overdue until done.

## Why not RRULE strings

An RRULE can express far more than a household uses, which makes it harder
to validate, harder to build a form for, and harder to explain in the UI.
Everything the structured fields cannot express (e.g. "the third weekday of
the month") has not been asked for.

## Why not generate occurrences ahead

A window of pre-generated rows has to be extended by a job, regenerated on
every schedule edit, and cleaned up when a chore is paused or deleted — and
none of it answers a question the one current occurrence doesn't. Upcoming
dates, when a screen wants them, are computed from the schedule.

## Why collapse misses

Agreed with David and Maddie on 2026-09-30. A week away from a daily chore
should leave one overdue item, not a wall of seven; the missed rows remain as
history.

## Consequences

- Screens apply the collapse on read (`occurrences.refresh()`, two queries
  for any number of chores) so they are never wrong because a scheduled run
  was skipped; `sweep_chores` records misses for chores nobody opened.
- Editing a schedule replaces the open occurrence. Editing anything else must
  not, or an overdue chore would be quietly reset.
- The semantics, with worked examples, are in
  [`household/docs/scheduling.md`](../../../household/docs/scheduling.md).

## Amendment — 2026-09-30, pre-merge review

**What the collapse looks like.** The text above (and the decision as first
described) said a week away from a daily chore "leaves one overdue item". It
doesn't: the newest arrived date opens, so the collapsed row is *due today*,
not overdue, and a daily chore without a deadline is never overdue at all.
The collapse itself is as agreed. To keep a missed week from being silent,
every checklist row now says "Missed N times before this" — the misses since
the last one done or skipped (`checklist.with_missed_streak`).

**Edits.** Review found three edit-path bugs, now fixed and tested:
editing or pausing/resuming never reopens a date already done or skipped
(a fresh start passes over closed dates); a schedule change records
`Chore.schedule_set_on`, and an occurrence limit — fixed or after-completion
— counts from there, so an edit can't use up "10 times" on dates before it;
and every edit form goes
through one atomic service, `occurrences.apply_edit`, which also notices a
one-off's deadline changing. A fixed schedule with no dates left from today
(or an after-completion one whose end date has passed) is refused by the
form rather than silently opening nothing.

**Every miss is recorded; no date is settled twice** (rounds 2–3). The
collapse used to mark only the open occurrence missed, so a week the sweep
didn't see left one missed row, and "Missed N" said 1. Now a missed row is
recorded for each date that came and went — by the collapse (up to a year's
worth at once), a late completion, or a schedule edit — which is what "the
missed rows remain as history" above always meant. And every path that
picks a fixed date passes over dates already done, skipped, or missed, so a
date done early is never reopened or recorded as missed beside its done row.
