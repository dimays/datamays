# Scheduling

How a chore repeats, when it is due, and what happens when it is done,
skipped, or ignored. The arithmetic is `household/scheduling.py` (pure
functions, no database); the lifecycle is `household/services/occurrences.py`.
The decision record is [ADR 0010](../../docs/architecture/decisions/0010-structured-schedules-one-open-occurrence.md).

## The two kinds of repeating chore

| | Fixed | After completion |
|---|---|---|
| Driven by | The calendar | The work |
| Example | Bins every Monday; mortgage-escrow check on the 1st | Furnace filter 90 days after it was last changed |
| If ignored | **Missed** when the next due date arrives | **Overdue** until done, however long |
| Next due date | The next calendar date after the one just closed | Interval after the household date it was done |

A **one-off** has a single occurrence, due on a date or "whenever".

## Schedule fields

| Field | Meaning |
|---|---|
| `frequency` | once · daily · weekly · monthly · yearly |
| `interval` | Every *n* units. After completion, the gap: `daily` + `90` = 90 days after |
| `starts_on` | First due date, and the phase: the weekday a weekly chore falls on, the day of the month a monthly one does. For a one-off, the due date, or blank for "whenever" |
| `weekdays` | Weekly, fixed only: any set of 0 (Mon) … 6 (Sun). Empty means `starts_on`'s weekday |
| `monthly_mode` | `day` (the 14th), `nth_weekday` (the second Saturday), `last_weekday` (the last Friday), all taken from `starts_on` |
| `anchor` | `fixed` or `after_completion` |
| `ends_on` | Last possible due date, inclusive |
| `max_occurrences` | Stop after this many |
| `season_start_month`, `season_end_month` | Only due within these months, inclusive. May wrap the new year (Nov–Feb) |
| `deadline` | One-off only: the hard "must be done by" |
| `deadline_offset_days` | Repeating only: each occurrence's deadline is due + this many days |

## Calendar rules

- **A day past a month's end lands on the last day.** Monthly on the 31st is
  Feb 28 (29 in a leap year), Apr 30, and so on. This is the reason for not
  using `dateutil.rrule`, which skips those months entirely.
- **February 29, yearly,** falls on the 28th in common years.
- **A fifth weekday that a month lacks is skipped.** "The fifth Tuesday"
  happens only in months that have one — as in a calendar app.
- **Weekdays before the start in the first week don't count.** Weekly on Mon
  and Fri starting on a Wednesday: the first is that Friday.
- **The season filters before the count.** "Ten times, April to October"
  means ten in-season dates.
- **The count starts when the schedule was set.** "Ten times" from a start
  date in June, for a chore made in September, means ten from September —
  dates before the chore existed don't use it up. Changing the schedule
  restarts the count from that day (`Chore.schedule_set_on`).
- **A fixed schedule with nothing left from today is refused** by the form
  (an end date or count already passed), rather than creating a chore that
  appears on no list.
- **Intervals are capped at ten years** in any unit, well short of the end of
  the calendar.
- **A schedule that can never fall in its season is refused.** Yearly on
  Jan 15 with an April–October season has no dates at all; validation says
  so rather than accepting a chore that would never appear.
- **"The last Friday" must start on a last Friday.** Otherwise the first due
  date would silently move later; validation asks for the right date instead.
- **An after-completion chore waits for its season.** Done in October with a
  90-day interval and an April–October season: next due April 1.

## The lifecycle

A chore has **at most one open occurrence**. The database enforces it
(`one_open_occurrence_per_chore`), so a double tap on "done" can never open
two.

**Starting.** Creating a chore opens its first occurrence. A fixed chore
whose `starts_on` is in the past starts at its next due date from today — it
does not arrive already overdue for dates before it existed. An
after-completion chore starts at `starts_on` even if that is past: "the
filter is due September 1" means it is overdue now.

**Done or skipped.** Records who (not necessarily the assignee), when, and an
optional note, then opens the next occurrence in the same transaction. For
after-completion chores, a skip restarts the clock just as done does.

**Missed.** When a fixed chore's next due date arrives and the current one is
still open, the current one becomes *missed* and the **newest** arrived date
opens — only the newest. A week away from a daily chore leaves one row, not
seven, and that row is **due today, not overdue**: the newest date is today.
Every date that came and went is still recorded as a missed row — whether
the sweep caught each one or a screen caught them all at once (up to a
year's worth) — so history is complete and the row can say **"Missed 7
times before this"**: the misses since the last one done or skipped. An
overdue fixed occurrence that a schedule edit replaces is recorded as
missed too, not erased. This happens at the next due
date even if the old occurrence's deadline has not passed, so a deadline
longer than the gap between due dates has no effect.

**Undo.** `reopen()` reverses the most recent done or skipped occurrence and
removes the untouched next one it opened. Anything older is history, and a
chore paused since can't be undone (it would hold an open occurrence no list
shows).

**A tap on a row that has moved on** — a phone left open overnight, while the
sweep recorded the row as missed — does nothing. The current row is swapped
in with a "moved on to its next date" note (or, without JavaScript, the same
as a message). Marking done something the other person just did says so,
rather than "Marked done".

**One-offs.** A done one-off stays done — unless it is given a new date
("do it again on the 10th"), which puts it back on the list. Converting a
repeating chore to a one-off does the same.

**Editing.** Every edit form goes through one service,
`occurrences.apply_edit(chore, before)`, atomically. It does nothing unless
something that decides the open occurrence changed — the schedule, whether
the chore is active, or a one-off's deadline — so tidying a title never
resets an overdue chore. When it does reschedule:

- a **fixed** chore starts from today, passing over any date already done,
  skipped, or missed (so editing a chore done today doesn't bring today's
  back, and one done early for Friday doesn't bring Friday back). Only those
  exact dates are passed over: a one-off done early and then made weekly
  still starts this week;
- an **after-completion** chore still counts from when it was last done —
  unless its due date was changed by hand, which is honored;
- a schedule change restarts any occurrence limit from today, for both
  anchors: only occurrences opened since the change count
  (`occurrences.occurrences_toward_limit`). The form refuses a changed
  schedule with nothing left to do — a fixed one with no dates left, or an
  end date already past.

**Pausing** (`is_active = False`) removes a repeating chore from every
checklist; resuming starts it afresh by the same rules.

## Overdue and "today"

An occurrence is **overdue** when it is open and its deadline — or its due
date, if it has no deadline — is before today. Due today is not overdue. An
undated one-off is overdue only if it has a deadline and that has passed;
it then shows as overdue everywhere, as the nav badge counts it.

"Today" is always `household_today()`, and a completion's date is its
*household* date: done at 10:30pm in Chicago counts for that day, not for
tomorrow in UTC.

## When the collapse runs

Twice, deliberately:

- **On read.** `refresh()` applies the missed-occurrence rule to chores
  already loaded, in bulk, writing only when something is stale — two queries
  whatever the number of chores. A screen is never wrong because the
  scheduler skipped a run. Two requests collapsing the same chore at once
  both end up showing the one row that opened.
- **Hourly.** `manage.py sweep_chores` applies it to every chore, so a missed
  week is recorded on the day it happened even if nobody opened the app. It
  runs in both scheduler chains, `household_hourly` and `household_daily`.

## Worked examples

| Chore | Fields | Due dates |
|---|---|---|
| Bins | weekly, `starts_on` Mon 2026-10-05 | Oct 5, 12, 19… |
| Water plants | weekly, `weekdays` [0, 3], every 2 | Mon + Thu every other week |
| Pay the sitter | monthly, `last_weekday`, `starts_on` Fri 2026-10-30 | Oct 30, Nov 27, Dec 25, Jan 29 |
| Hose valve on | yearly, `starts_on` 2027-04-15, `deadline_offset_days` 14 | Apr 15 each year, deadline Apr 29 |
| Furnace filter | daily, `interval` 90, after completion | 90 days after each change |
| Mow | weekly, after completion, season Apr–Oct | A week after each mow, April to October |
| Renew plates | once, `starts_on` Oct 1, `deadline` Oct 31 | Shows from Oct 1, overdue after Oct 31 |
