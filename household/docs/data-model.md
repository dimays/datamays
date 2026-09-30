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

| `project` → Project, `milestone` → Milestone | Set for a project's task. A task is household-owned; `clean()` checks the milestone is in the same project |

A maintenance chore is reached the other way, through
`MaintenanceItem.chore` (`chore.is_maintenance`).

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
| `cost` | What doing it cost, positive `Decimal`, or null — mostly logged for maintenance |
| `transaction` → finance.Transaction | The purchase behind a maintenance job; cleared if the transaction is deleted |

**Constraint:** `one_open_occurrence_per_chore` — a partial unique index on
`chore` where `status = 'open'`. The lifecycle depends on it.

**Ordering:** by `due_on` with nulls last, explicitly. SQLite and Postgres
disagree about where NULL sorts, so the local server and production would
otherwise disagree about where "whenever" chores go.

`is_overdue(today)`, `days_overdue(today)`, and `effective_deadline()` are
the one definition of overdue; see [scheduling.md](scheduling.md#overdue-and-today).

## MaintenanceItem

Shared upkeep. `household/models/maintenance.py`; see
[maintenance.md](maintenance.md).

| Field | |
|---|---|
| `chore` → Chore | One-to-one. The name, schedule, assignee, and history live there; the chore is household-owned |
| `area` | HVAC, plumbing, electrical, safety, appliances, exterior, yard, cleaning, other |
| `location`, `instructions`, `supplies`, `supply_url` | |
| `estimated_cost` | What it usually costs, positive `Decimal`; prefills the cost when logging a job |

Money columns use `household/models/base.py::money_field`, the same shape
as finance's (ADR 0002) — restated rather than imported (ADR 0009).

## Project, Milestone, ProjectLink, ProjectNote

`household/models/projects.py`; see [projects.md](projects.md).

| Model | Fields |
|---|---|
| `Project` | `name`, `summary`, `status` (active · planned · idea · on_hold · done), `start_on`, `target_on`, `budget_total` (positive `Decimal`), `created_by` |
| `Milestone` | `project`, `name`, `target_on`, `completed_on` — ordered by date with undated last, explicitly |
| `ProjectLink` | `project`, `title`, `url` (a `URLField`: http, https, ftp only) |
| `ProjectNote` | `project`, `author`, `body` — newest first |

## BudgetLine, ProjectExpense

`household/models/budgets.py`; see [finance-bridge.md](finance-bridge.md).

| Model | Fields |
|---|---|
| `BudgetLine` | `project`, `label`, `estimated` (positive `Decimal`) |
| `ProjectExpense` | `project`, `budget_line` (optional; nulled if the line is removed), `transaction` → finance.Transaction (deleted with it). Unique per project and transaction |

## HouseholdPreference

Per-person settings for the household sections; finance keeps its own.

| Field | |
|---|---|
| `user` → User | One-to-one |
| `show_partner_chores` | The "Show Maddie's chores" switch on Today and the checklist |
| `share_new_chores` | Default for a new chore's "let the other person manage it" |
| `morning_digest` | Opt-in to the morning email |
| `last_digest_on` | Household date of the last digest (or empty morning) — one per day |

## Relationships at a glance

```
User ─┬─< Chore (owner)          null owner = household-owned
      ├─< Chore (assignee)       null assignee = either of us
      └─< Occurrence (completed_by)

Chore ─< Occurrence              at most one open at a time
Chore ─── MaintenanceItem        one-to-one, for shared upkeep
Project ─< Chore (tasks)          a task is a household chore
Project ─< Milestone ─< Chore     optional
Project ─< ProjectLink, ProjectNote
Project ─< BudgetLine ─< ProjectExpense ─> finance.Transaction
Occurrence ─> finance.Transaction      optional, maintenance jobs
```
