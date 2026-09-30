# Mays Household

The private household app for David and Maddie. It wraps the existing
[finance app](../../finance/docs/README.md) in a shared shell — one sign-in,
one navigation bar, one Today screen — and adds three sections of its own:
**Chores**, **Projects**, and **Maintenance**.

It is being built in phases on stacked `household/*` branches. The plan,
including the agreed decisions and the definition of done, is
[`docs/plans/household.md`](../../docs/plans/household.md). These docs grow
with each phase and describe only what has actually been built.

## Status

| Phase | Branch | State |
|---|---|---|
| 0 — Foundation | `household/foundation` | App skeleton, local settings, demo seed |
| 1 — Shell | `household/shell` | Not started |
| 2 — Scheduling | `household/scheduling` | Not started |
| 3 — Chores | `household/chores` | Not started |
| 4 — Maintenance | `household/maintenance` | Not started |
| 5 — Projects | `household/projects` | Not started |
| 6 — Finance bridge | `household/finance-bridge` | Not started |
| 7 — Notifications | `household/notifications` | Not started |
| 8 — Polish | `household/polish` | Not started |

## Vocabulary

The same words in code, UI, and docs.

| Term | Meaning |
|---|---|
| **Section** | One top-level area: Today, Chores, Projects, Maintenance (shown as "Upkeep" in the nav), Finance. |
| **Chore** | Anything on a person's checklist — one-off or recurring. The universal unit of "a thing to do". |
| **Occurrence** | One dated instance of a chore. |
| **Schedule** | How a chore repeats: *fixed* ("every Monday") or *after completion* ("90 days after it was last done"). |
| **Due date / deadline** | Due is when it should be done and when it appears; deadline is the hard "must be done by". |
| **Maintenance item** | A shared home-upkeep definition — what, where, how, supplies, cadence, cost. It produces chores. |
| **Project** | A longer-term shared effort with milestones, a budget, links, and tasks. |
| **Project task** | A chore that belongs to a project. Assigning it puts it on someone's checklist. |
| **Owner / assignee** | Owner controls a chore; assignee is whose checklist it is on. |

## Running it locally

Never point `runserver` at the default settings — the local `.env` targets
production. Use the local settings and the demo household instead:

```bash
uv run python manage.py migrate --settings=datamays.settings_local
```

```bash
uv run python manage.py seed_household_demo --settings=datamays.settings_local
```

```bash
uv run python manage.py runserver --settings=datamays.settings_local
```

Sign in as `david` or `maddie` with `DEMO_PASSWORD` from
[`services/demo.py`](../services/demo.py). For the second factor:

```bash
uv run python manage.py demo_totp_code david --settings=datamays.settings_local
```

`seed_household_demo --reset` wipes and reseeds. Both commands refuse to run
against anything but SQLite.

## Layout

```
household/
  models/       One module per domain (arrives with the scheduling phase)
  services/     Logic; demo.py builds the local demo household
  management/commands/   seed_household_demo, demo_totp_code
  tests/        One file per feature area
  docs/         You are here
```

## Decisions

- [ADR 0008](../../docs/architecture/decisions/0008-household-shell-owns-sign-in.md) —
  a household shell owns sign-in and navigation; finance becomes a section
- [ADR 0009](../../docs/architecture/decisions/0009-one-household-app-one-finance-bridge.md) —
  one app for chores, maintenance, and projects; finance is reached through
  one module
