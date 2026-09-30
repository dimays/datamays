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
| 1 — Shell | `household/shell` | Sign-in, access gate, page chrome, section nav, Today with the budget widget |
| 2 — Scheduling | `household/scheduling` | Schedule arithmetic, `Chore` / `Occurrence`, the occurrence lifecycle, `sweep_chores` |
| 3 — Chores | `household/chores` | Checklists, the chore form with live preview, one-tap done/skip/undo, permissions, Today's chore sections, overdue badge |
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

Sign in at `/household/login/` as `david` or `maddie` with `DEMO_PASSWORD` from
[`services/demo.py`](../services/demo.py). For the second factor:

```bash
uv run python manage.py demo_totp_code david --settings=datamays.settings_local
```

`seed_household_demo --reset` wipes and reseeds. Both commands refuse to run
against anything but SQLite.

## The docs

| | |
|---|---|
| [`architecture.md`](architecture.md) | The shell, the dependency rules, sign-in, navigation. **Read first if you are changing code.** |
| [`scheduling.md`](scheduling.md) | How chores repeat: fixed vs. after-completion, missed vs. overdue, the lifecycle, worked examples |
| [`permissions.md`](permissions.md) | Who may see, complete, and manage a chore |
| [`data-model.md`](data-model.md) | Every model and the relationships that matter |
| [`screens.md`](screens.md) | Every URL, its view, and its template |

## Decisions

- [ADR 0008](../../docs/architecture/decisions/0008-household-shell-owns-sign-in.md) —
  a household shell owns sign-in and navigation; finance becomes a section
- [ADR 0009](../../docs/architecture/decisions/0009-one-household-app-one-finance-bridge.md) —
  one app for chores, maintenance, and projects; finance is reached through
  one module
- [ADR 0010](../../docs/architecture/decisions/0010-structured-schedules-one-open-occurrence.md) —
  structured schedules, one open occurrence per chore, missed occurrences
  collapse
- [ADR 0011](../../docs/architecture/decisions/0011-chore-permissions.md) —
  chores are owner-managed; either person may mark one done
