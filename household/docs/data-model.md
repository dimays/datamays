# Data model

Every household model and the relationships that matter. Money, when it
arrives with maintenance and projects, follows finance's rules — `Decimal`
only, the household sign convention (ADR 0002, 0003).

## Chore

Anything on someone's checklist. `household/models/chores.py`.

| Field | |
|---|---|
| `title`, `notes` | |
| `owner` → User | Who controls it. **Null means household-owned** — shared work either person manages |
| `assignee` → User | Whose checklist it is on. Null means either person |
| `others_can_manage` | The per-chore grant: lets the other person edit, skip, or delete it |
| schedule fields | `frequency`, `interval`, `starts_on`, `weekdays`, `monthly_mode`, `anchor`, `ends_on`, `max_occurrences`, `deadline`, `deadline_offset_days`, `season_start_month`, `season_end_month` — see [scheduling.md](scheduling.md) |
| `is_active` | False pauses a repeating chore: it leaves every checklist |

`chore.schedule` assembles the schedule fields into a
`scheduling.Schedule`; `chore.describe_schedule()` renders it in words.
`Chore.clean()` runs `scheduling.validate()` plus the checks that need both
halves of a pair (season months, one-off vs. repeating deadlines).

Arriving in later phases: links to the maintenance item or project (and
milestone) a chore came from.

## Occurrence

One dated instance of a chore.

| Field | |
|---|---|
| `chore` → Chore | |
| `due_on` | Null for a one-off due whenever |
| `deadline` | Copied from the chore (one-off) or computed from `deadline_offset_days` (repeating) when opened, so editing the chore later doesn't rewrite history |
| `status` | `open` · `done` · `skipped` · `missed` |
| `completed_by` → User | Who actually did it — may not be the assignee |
| `completed_at` | Aware datetime; its *household* date is what after-completion schedules count from |
| `note` | |

**Constraint:** `one_open_occurrence_per_chore` — a partial unique index on
`chore` where `status = 'open'`. The lifecycle depends on it.

**Ordering:** by `due_on` with nulls last, explicitly. SQLite and Postgres
disagree about where NULL sorts, so the local server and production would
otherwise disagree about where "whenever" chores go.

`is_overdue(today)`, `days_overdue(today)`, and `effective_deadline()` are
the one definition of overdue; see [scheduling.md](scheduling.md#overdue-and-today).

## Relationships at a glance

```
User ─┬─< Chore (owner)          null owner = household-owned
      ├─< Chore (assignee)       null assignee = either of us
      └─< Occurrence (completed_by)

Chore ─< Occurrence              at most one open at a time
```
