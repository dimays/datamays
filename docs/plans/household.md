# Plan: from Household Finance to Household

Status: **agreed** · Branch: `feature/household` · Drafted and agreed 2026-09-30

The finance app becomes one section of a wider private household app for
David and Maddie. Three new sections join it — **Chores**, **Projects**,
**Maintenance** — behind the same sign-in, in the same visual language, and
with money surfaced where it genuinely answers a question.

This document covers what gets built, in what order, how it is documented,
how quality is enforced, and what "done" means. Decisions that need a call
from you are recorded at the end under [Decisions](#decisions).

---

## 1. Guiding constraints

These are inherited from the finance app and not up for renegotiation here:

- **Two users.** No multi-household support, no roles beyond "member".
  Generality that only pays off at scale is a cost.
- **Phone first.** "What do I need to do today?" answered in one tap, the
  same way "can we afford this?" is today.
- **Dark-only, same tokens and component classes.** No new design system.
- **Server-rendered Django + htmx + Alpine.** No SPA, no new JS dependency
  unless a screen genuinely cannot be built without one.
- **"Today" is the household's today** (`America/Chicago`), never UTC.
- **Nothing reaches production until the whole stack is reviewed**, because
  merging to `main` deploys.

---

## 2. Vocabulary

Fixed now so code, UI, and docs all use the same words.

| Term | Meaning |
|---|---|
| **Mays Household** | The whole app. The shell that owns sign-in, navigation, and the Today screen. |
| **Section** | One top-level area: Today, Chores, Projects, Maintenance, Finance. |
| **Chore** | Anything on a person's checklist — one-off or recurring. The universal unit of "a thing to do". |
| **Occurrence** | One dated instance of a chore. A weekly chore has one occurrence per week. |
| **Schedule** | How a chore repeats. Either *fixed* ("every Monday") or *after completion* ("90 days after it was last done"). |
| **Due date / deadline** | Due is when it should be done and when it appears; deadline is the hard "must be done by". Either is optional. |
| **Maintenance item** | A shared home-upkeep definition — what, where, how, supplies, cadence, expected cost. It produces chores. |
| **Project** | A longer-term shared effort with milestones, a budget, links, and tasks. |
| **Project task** | A chore that belongs to a project (and optionally a milestone). Assigning it puts it on someone's checklist — that is what "tasks become chores" means mechanically. |
| **Owner / assignee** | Owner controls a chore; assignee is whose checklist it appears on. For a personal chore they are the same person. |

---

## 3. Architecture

### 3.1 Apps and dependency direction

```
household/   NEW  The shell + the three new sections
  access.py        the gate (moved from finance), member helpers
  dates.py         household_today() (moved from finance; finance re-exports)
  scheduling.py    pure recurrence arithmetic — no database access
  models/          chores, maintenance, projects, prefs
  services/        occurrences, permissions, today, digest, finance bridge
  integrations/finance.py   the ONLY module in household that imports finance
  views/ forms/ templates/household/ management/commands/ tests/ docs/
finance/     EXISTING  Unchanged in behavior; becomes a section of the shell
core/ contact/   Untouched
```

Dependency rules, enforced by a test that parses imports:

- `finance` may import only `household.access`, `household.dates`, and the
  shell's templates. It never learns chores or projects exist.
- `household` reaches finance only through `household/integrations/finance.py`,
  and only reads (plus writing its *own* link rows that point at finance
  transactions). It never writes a finance model. The local demo seed is
  the one exception — it exists to build finance data, and only on SQLite.

Why one new app rather than three: chores, maintenance, and project tasks all
share one schedulable unit and one permission model. Splitting them into
separate Django apps would put the seam exactly where the coupling is
tightest. Inside the app they stay separated the way finance does it — one
module per domain under `models/`, `services/`, `views/`, `forms/`.

Why not rename `finance` to `household`: renaming a Django app rewrites
table names, content types, permissions, and migration history on a live
database holding real balances. It buys nothing a shell app does not.

### 3.2 URLs

| Path | What |
|---|---|
| `/household/` | Today screen (new landing page after sign-in) |
| `/household/chores/…` | Chores |
| `/household/projects/…` | Projects |
| `/household/maintenance/…` | Maintenance |
| `/household/login/`, `/household/two-factor/…` | Sign-in (moved) |
| `/finance/…` | **Unchanged.** Email reports and bookmarks keep working. |

Old `/finance/login/` and `/finance/two-factor/` paths redirect to the new
ones. `LOGIN_URL` and `LOGIN_REDIRECT_URL` move to the household namespace.

### 3.3 Sign-in and access

- The three gates stay exactly as they are — authenticated → household
  member → cleared TOTP — and the first two still answer with a **403, not a
  redirect**, for every `/household/` path as well as `/finance/`.
- The `finance` group is renamed `household` by a data migration. Both
  existing users keep their passwords and TOTP devices — no re-enrollment.
- One session covers every section. Clearing TOTP once is enough.
- `django-axes` lockout behavior is unchanged.

### 3.4 Shell, navigation, and styling

- `household/base.html` becomes the one base template; `finance/base_finance.html`
  extends it, so the header, messages, and page chrome are identical everywhere.
- Header brand and page titles become **Mays Household**.
- **Navigation becomes two-level:**
  - Global bottom tab bar on phones / header links on desktop:
    **Today · Chores · Projects · Upkeep · Finance**.
  - Each section has its own sub-navigation as a horizontal pill strip under
    the header. Finance's current six items (Home, Activity, Charts, QFRs,
    Import, Settings) move there.
- The account menu gains a section-independent Preferences page; finance
  preferences stay where they are.
- New icons follow the existing `templates/finance/icons/` pattern (moved to
  a shared location).
- Existing component classes (`page-title`, `page-subtitle`, `empty-state`, …)
  are reused; any new repeated class string gets named in
  `assets/css/input.css` and added to the UI-conventions test.

### 3.5 Scheduling — the core of Chores and Maintenance

Structured fields rather than raw RRULE strings: they validate cleanly,
render as a normal form, and cover what a household actually needs. The
arithmetic is our own small pure functions — *not* `dateutil.rrule`, which
skips months lacking the requested day, so "monthly on the 31st" would not
happen in February (changed during phase 2; see ADR 0010).

| Field | Values |
|---|---|
| `frequency` | once · daily · weekly · monthly · yearly |
| `interval` | every N units (every 2 weeks, every 3 months) |
| `weekdays` | for weekly: any set of weekdays |
| `monthly_mode` | day-of-month (with "last day") or nth weekday ("second Saturday", "last Friday") |
| `anchor` | **fixed** — calendar-driven; **after completion** — next due is N units after the last completion |
| `starts_on` / `ends` | never · until a date · after N occurrences |
| `deadline_offset_days` | optional: each occurrence's deadline is due + N days |
| `season` | optional month window, for "only April–October" |

Occurrence lifecycle:

- A recurring chore keeps **exactly one open occurrence** — the current one.
  Completing or skipping it creates the next in the same database
  transaction.
- If a *fixed* schedule's next due date arrives while the current one is still
  open, the stale one is marked **missed** and the new one opens. Missed
  daily chores do not pile up into a wall of red.
- *After-completion* schedules never miss — they just become overdue, because
  the clock only restarts when the work is done. That is the right model for
  filters and deep cleans.
- Completion records who, when, and an optional note; maintenance
  completions can also carry a cost and a linked finance transaction.

`household/scheduling.py` is pure functions over dates — no ORM — so the
edge cases get exhaustive tests the way `finance/periods.py` does: month-end
anchors (31st in February), leap days, "fifth Tuesday" in a four-Tuesday
month, DST transitions, and the household-midnight boundary.

A sweep runs on the existing hourly schedule to roll fixed schedules
forward, but screens never depend on it having run — they compute the
current state on read, so a skipped scheduler run cannot show stale chores.

### 3.6 Data model sketch

Final field lists land with each phase; this is the shape.

```
Chore
  title, notes
  owner → User            who controls it (null = household-owned)
  assignee → User         whose checklist (null = "either of us")
  others_can_manage       the per-chore sharing grant
  schedule fields (3.5)   or none, for a one-off
  due_on, deadline        for one-offs
  project → Project?      provenance, for project tasks
  milestone → Milestone?
  maintenance_item → MaintenanceItem?
  is_active

Occurrence
  chore → Chore
  due_on, deadline
  status: open | done | skipped | missed
  completed_by → User?, completed_at, note
  cost (money_field)?, transaction → finance.Transaction?

MaintenanceItem
  name, area (HVAC, plumbing, exterior, appliances, cleaning, …), location
  instructions, supplies (e.g. "16x25x1 MERV 11") with optional purchase URL
  estimated_cost, finance category (default housing-maintenance)
  → owns one recurring Chore (household-owned, assignee optional)

Project
  name, summary, status: idea | planned | active | on hold | done
  start_on, target_on, budget_total
Milestone        project, name, target_on, completed_on, order
ProjectLink      project, title, url  (Drive docs, quotes, inspiration)
BudgetLine       project, label, estimated, finance category?
ProjectExpense   project, budget_line?, transaction → finance.Transaction
                 (a household-side link row — finance tables are not altered)
ProjectNote      project, author, body, created_at  (decisions log)

HouseholdPreference   user, chore defaults, show-partner toggle state,
                      digest opt-in, Today-screen widgets
```

### 3.7 The Today screen

The landing page after sign-in, and the one screen that pulls every section
together. Top to bottom on a phone:

1. **Overdue** — anything past its deadline (or past its due date when it has
   none), yours first, then household-owned. Unmistakable: a red count badge
   in the section header, a red left border and "3 days overdue" on each row,
   and the same count as a badge on the Chores tab in the nav so it is
   visible from every screen.
2. **Today** — your chores due today, each checkable in one tap.
3. **Coming up in the next 7 days** — one-off and low-frequency chores
   (anything repeating less often than weekly: monthly, quarterly, yearly,
   and after-completion maintenance) so the filter change or the registration
   renewal is seen before it is due, not on the day. Daily and weekly chores
   are left out here — they are routine and would drown the rest.
4. **Budgets** — finance's existing budget widget, the same builder and
   template the finance homepage uses, respecting each person's
   budget selection in finance preferences. This keeps "can we afford this?"
   one tap from sign-in.
5. **Projects** — active projects with their next milestone *(from phase 5)*.

The partner toggle applies here too: switched on, the other person's overdue
and due-today chores show in a separate, read-only-except-complete group.

### 3.8 Chore permissions

Agreed rule: each person manages only their own chores unless explicitly
granted; both can *see* both lists, behind a toggle.

- **See:** your checklist by default; a "Show Maddie's" / "Show David's"
  toggle reveals the other list read-only. The toggle state persists per
  person.
- **Complete:** either of you can mark the other's chore done — the "I took
  the trash out for you" case. Because it is someone else's list, a
  confirmation dialog asks first ("Mark Maddie's *Take out trash* as done?"),
  and the occurrence records who actually did it. Your own chores complete in
  one tap, no dialog.
- **Manage** (edit, delete, skip, reschedule): the owner, or anyone when
  `others_can_manage` is on for that chore. Each person sets a default for
  new chores in preferences.
- **Household-owned chores** (from maintenance items and projects) are
  manageable by both, always — the shared work is shared.
- Enforced in exactly one place, `services/permissions.py`, which every view
  and every htmx endpoint calls. The confirmation dialog is UX, not the
  guard — the server-side check is what a test proves. A table-driven test
  covers every action × (owner, partner without grant, partner with grant,
  household-owned, outsider, anonymous).

### 3.9 Finance integration

| Where | What it shows |
|---|---|
| Same session, users, TOTP, styling | Covered by the shell |
| **Today screen** | Finance's existing budget widget, reused as-is (see 3.7) |
| **Project → Budget** | Budget lines with estimates; actuals from linked transactions; variance using the existing budget-bar partial. "Suggest expenses" lists recent transactions in Home Improvement / Maintenance categories within the project's dates, one tap to link |
| **Maintenance → History** | Cost per completion (typed or linked transaction); spend per item per year |
| **Maintenance → Upcoming costs** | Estimated cost of maintenance due in the next 90 days / 12 months |

All money goes through `money_field()` and `Decimal`; linked transactions
reuse finance's sign convention and display filters.

### 3.10 Notifications

An opt-in **morning digest email** per person — today's chores, overdue
items, maintenance due this week, project milestones within 14 days. Uses
the existing Gmail SMTP setup.

To keep Heroku Scheduler at two entries (ADR 0006), new wrapper commands
`household_hourly` / `household_daily` call finance's chains and then the
household steps; the scheduler entries are swapped to them. The digest runs
from the hourly chain and sends once per household-local morning, which is
DST-proof in a way a fixed UTC cron time is not.

### 3.11 Local development and QA data

Browser QA needs a server that does not touch production. Add
`datamays/settings_local.py` (file-based SQLite, Sentry off, console email)
and `manage.py seed_household_demo`, which creates two demo members and a
realistic fake household — chores, a kitchen project, a maintenance library,
and finance demo data. The repo is public, so it is entirely fictional.

---

## 4. Build phases

Stacked branches, matching the finance app's convention: `feature/household`
is the base off `main`, and each phase branches from the previous one with a
PR targeting it. `feature/household` merges to `main` once, at the end.

| # | Branch | Delivers | Done when |
|---|---|---|---|
| 0 | `household/foundation` | App skeleton, `settings_local`, demo seed, docs skeleton, ADRs drafted, this plan finalized | App installs, local server runs on SQLite, finance suite green |
| 1 | `household/shell` | Auth + dates move, group rename migration, shared base template, two-level nav, Today screen with the finance budget widget, import-boundary test | Existing users sign in unchanged; every finance screen looks and behaves as before apart from nav; 403 posture holds on every route |
| 2 | `household/scheduling` | `scheduling.py`, `Chore` / `Occurrence`, occurrence services, hourly sweep | Boundary test suite passes; next-occurrence logic proven for fixed and after-completion |
| 3 | `household/chores` | My checklist, partner toggle, create/edit (schedule builder form), one-tap complete/skip via htmx, partner-completion confirmation, history, sharing grant, Today's overdue / today / next-7-days sections and the nav overdue badge | Permission matrix test green; a recurring chore can be created and completed on a 375px screen in under 30 seconds |
| 4 | `household/maintenance` | Maintenance items, areas, supplies, seasonal windows, completion log with cost, a short starter library | Hose-valve on/off, 90-day filter, and annual deep clean all expressible and demonstrated |
| 5 | `household/projects` | Projects, milestones, timeline, links, notes, tasks-as-chores | Assigning a project task makes it appear on that person's checklist; timeline renders on phone and desktop |
| 6 | `household/finance-bridge` | Project budgets + expense linking, maintenance cost history + upcoming costs | Actuals reconcile to linked transactions to the cent; import-boundary test still green |
| 7 | `household/notifications` | Digest email, preferences, `household_hourly` / `household_daily` | One digest per person per morning across a DST boundary in tests |
| 8 | `household/polish` | In-app Help for every section, docs pass, full QA sweep, query-budget ceilings, accessibility pass | Section 7's definition of done |

Each phase ends the same way: tests → docs updated in the same branch →
browser QA at phone and desktop widths with screenshots in the PR →
`/code-review` → PR opened against its predecessor for your review.
Phase 1 also gets `/security-review`, because it moves the auth gate.

---

## 5. Documentation

Following the pattern the repo already has:

**New — `household/docs/`**

| File | Contents |
|---|---|
| `README.md` | What it is, the vocabulary table, where to start |
| `architecture.md` | Layout, dependency rules, shell vs. sections |
| `data-model.md` | Every model and the relationships that matter |
| `scheduling.md` | Recurrence semantics precisely: fixed vs. after-completion, missed vs. overdue, deadlines, seasons, worked examples |
| `permissions.md` | The see/manage matrix, and where it is enforced |
| `screens.md` | Every URL → view → template |
| `extending.md` | Recipes: add a schedule option, a Today widget, a maintenance area |
| `runbook.md` | Scheduler, digest troubleshooting, the group migration |

**Updated — repo docs**

- `docs/README.md`, `docs/architecture/overview.md` — four apps, the shell,
  the new request flow; the "scope" note widened from finance to household.
- `docs/conventions.md` — dates rule and view mixins become household-wide.
- `docs/onboarding.md`, `docs/runbooks/deploy.md` — `settings_local`, demo
  seed, new scheduler commands.

**New ADRs**

- 0008 — A household shell owns sign-in and navigation; finance becomes a section
- 0009 — One app for chores, maintenance, and projects; finance is reached through one module
- 0010 — Structured schedules, one open occurrence per chore, fixed vs. after-completion
- 0011 — Chore permissions: owner-managed, per-chore grant, household-owned is shared
- Amend 0004 (household today is now app-wide) and 0006 (the wrapper commands)

**In-app Help** — each section gets a Help entry written for you and
Maddie, not developers, like finance's today.

---

## 6. Quality

**Automated, run on every phase**

- Full suite with `--settings=datamays.settings_test`, finance included —
  finance's 9.5k lines of tests are the regression net for the shell move.
- `scheduling.py` boundary tests at the standard of `test_periods.py`.
- **Every-route gate test** that walks the URL resolver, so a new household
  view that forgets the access mixin fails without anyone remembering to add
  it to a list.
- **Permission matrix test** (3.8), table-driven.
- **Import-boundary test** (3.1).
- **Query budgets** for Today, Chores, Projects, Maintenance — cost must not
  grow with the number of chores, occurrences, or projects.
- Existing repo-wide guards apply automatically: US spelling, UI component
  classes, committed CSS is current, `makemigrations --check`.
- Network isolation: the digest never sends real mail in tests.

**Manual, per phase**

- Browser QA against the demo seed at 375px and desktop, screenshots in PR.
- Keyboard and screen-reader basics: labels on every control, focus visible,
  htmx swaps announce state changes.
- `/code-review` on each PR; `/security-review` on the shell PR.

**Before merging to `main`**

- Rehearse the group-rename migration against a copy of production data
  structure (not a production connection).
- Deploy one merge at a time per the deploy runbook; verify deployed content,
  not just the release number.

---

## 7. Definition of done

The whole effort is done when all of these are true:

1. Every phase's "done when" criterion is met and its PR is merged into
   `feature/household`, then `feature/household` into `main`.
2. Production is running it: both of you sign in with your existing
   passwords and TOTP, land on Today, and every finance screen and email
   link still works.
3. Scheduler entries point at the new wrapper commands and the first digest
   has arrived.
4. These scenarios work end-to-end on a phone, demonstrated with
   screenshots:
   - Create a weekly chore, complete it, see next week's appear.
   - See the other person's chores via the toggle; be refused edits until
     they share one; then edit it.
   - Set the furnace filter to 90 days after completion; log a replacement
     with its cost linked to a real transaction.
   - Create a project with a budget, two milestones, a Drive link, and a
     task assigned to Maddie that shows on her checklist.
   - Link three transactions to the project and see actual vs. budget.
   - Open Today and see the budget widget, an overdue chore clearly flagged,
     and a quarterly chore due in five days under "Coming up".
   - Mark the other person's chore done after the confirmation dialog.
   - Receive a morning digest.
5. The full test suite passes, docs and ADRs describe what shipped, and
   in-app Help covers every section.
6. **Yours to call:** a week of real use by both of you without a blocking
   issue. I can verify 1–5; this one is yours.

---

## 8. Deliberately out of scope (for now)

Recorded so the answer to "why doesn't it…" is on file:

- **Google Drive or Calendar API integration** — links only. A private,
  tokenized ICS feed of chores for Google Calendar is the most likely
  follow-up and is cheap.
- **File and photo uploads** — Heroku's disk is ephemeral and there is no
  object storage configured. Drive links cover it.
- **Push notifications / installable app** — email digest first.
- **Time-of-day reminders** — schedules are date-based.
- **Chore rotation, points, streaks** — a household of two can talk.
- **Weather-triggered maintenance** ("before the first freeze") — fixed dates
  with a deadline window stand in for it.
- **Light theme, SMS, multiple households** — unchanged from finance.

---

## Decisions

Agreed 2026-09-30.

| # | Question | Decision |
|---|---|---|
| 1 | Navigation | Global section bar (Today · Chores · Projects · Upkeep · Finance); each section has its own sub-nav |
| 2 | Checking off the other person's chore | Allowed for both of you, behind a confirmation dialog, recorded as done-by. Edit/delete stay with the owner unless shared |
| 3 | Missed recurring chores | Collapse into one current occurrence; older ones marked missed |
| 4 | Name | **Mays Household** |
| 5 | Finance URLs | Stay at `/finance/…` |
| 6 | Starter maintenance library | Yes — start simple, a short generic list |
| 7 | Review cadence | Each phase's PR is reviewed as it lands |

Feedback folded in: the Today screen carries finance's budget widget, a
next-7-days list of one-off and low-frequency chores, and clear overdue
indicators (3.7).
