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
opens — only the newest. A week away from a daily chore leaves one overdue
item, not seven. This happens at the next due date even if the old
occurrence's deadline has not passed.

**Undo.** `reopen()` reverses the most recent done or skipped occurrence and
removes the untouched next one it opened. Anything older is history.

**Editing.** Changing a schedule replaces the open occurrence with a fresh
one from today (an after-completion chore still counts from when it was last
done). Editing only the title or notes must *not* call `reschedule()` — it
would reset an overdue chore. **Pausing** (`is_active = False`) removes a
repeating chore from every checklist; resuming starts it afresh.

## Overdue and "today"

An occurrence is **overdue** when it is open and its deadline — or its due
date, if it has no deadline — is before today. Due today is not overdue. An
undated one-off is never overdue.

"Today" is always `household_today()`, and a completion's date is its
*household* date: done at 10:30pm in Chicago counts for that day, not for
tomorrow in UTC.

## When the collapse runs

Twice, deliberately:

- **On read.** `refresh()` applies the missed-occurrence rule to chores
  already loaded, in bulk, writing only when something is stale — two queries
  whatever the number of chores. A screen is never wrong because the
  scheduler skipped a run.
- **Hourly.** `manage.py sweep_chores` applies it to every chore, so a missed
  week is recorded on the day it happened even if nobody opened the app. It
  joins the hourly scheduler chain in the notifications phase.

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
