# Screens

Every household URL, its view, and its template. `household/urls.py` is the
truth if this drifts. Paths are relative to `/household/`; templates to
`household/templates/household/`.

## Sign-in

| Path | View | Template | Gate |
|---|---|---|---|
| `login/` | `HouseholdLoginView` | `login.html` | none |
| `logout/` | `HouseholdLogoutView` | — POST only, then the public site | none |
| `two-factor/setup/` | `OTPSetupView` | `otp_setup.html` | member, not yet verified |
| `two-factor/` | `OTPVerifyView` | `otp_verify.html` | member, not yet verified |

The two TOTP screens use `PageTitleMixin` + `HouseholdMemberMixin` rather
than the full gate — they need a title but cannot require a cleared second
factor, since they are how you clear it.

The pre-shell paths `/finance/login/`, `/finance/two-factor/`, and
`/finance/two-factor/setup/` redirect here, keeping any `?next=`.

## Sections

Everything here is behind the full gate.

| Path | View | Template |
|---|---|---|
| `` (root) | `TodayView` | `today.html` |
| `chores/` | `ChecklistView` | `chores/checklist.html` |
| `chores/all/` | `ChoreListView` | `chores/all.html` — every chore, paused and finished included |
| `chores/new/` | `ChoreCreateView` | `chores/form.html` |
| `chores/<pk>/` | `ChoreDetailView` | `chores/detail.html` — now, the next few dates, history |
| `chores/<pk>/edit/` | `ChoreUpdateView` | `chores/form.html` — managers only |
| `chores/<pk>/delete/` | `ChoreDeleteView` | `chores/confirm_delete.html` — managers only |
| `chores/preview/` | `SchedulePreviewView` | `chores/_schedule_preview.html` — the form's live "what this means" (htmx GET) |
| `preferences/` | `HouseholdPreferencesView` | `preferences.html` — per-person chore settings; finance's are at `/finance/preferences/` |
| `chores/partner/` | `PartnerToggleView` | — POST, flips "show the other person's chores", redirects back |
| `occurrences/<pk>/<action>/` | `OccurrenceActionView` | `chores/_row.html` or `_row_closed.html` — POST `complete`, `skip`, or `undo` |

### One-tap actions

A checklist row is `chores/_row.html`. Its circle POSTs `complete`; with
htmx, the response replaces the row with `_row_closed.html` (done or
skipped, the next due date, and Undo), and Undo swaps the open row back.
Without JavaScript the same forms POST and redirect to the page's `next`.
Permission for each action is `services/permissions.py`'s decision — see
[permissions.md](permissions.md).

### Today

Top to bottom: **Overdue** (yours and shared, most late first, in a red
panel with a count), **Today**, **Coming up this week** (only one-offs and
chores repeating a fortnight apart or more — `scheduling.is_low_frequency`),
the other person's overdue and due-today items when the toggle is on, then
finance's **budget widget**. The Chores section's nav item carries the
overdue count on every page, finance included.

## Projects

All behind the full gate, and open to both members.

| Path | View | Template |
|---|---|---|
| `projects/` | `ProjectListView` | `projects/list.html` — grouped by status |
| `projects/new/` | `ProjectCreateView` | `projects/form.html` |
| `projects/<pk>/` | `ProjectDetailView` | `projects/detail.html` — progress, timeline, tasks, links, notes |
| `projects/<pk>/edit/` | `ProjectUpdateView` | `projects/form.html` |
| `projects/<pk>/delete/` | `ProjectDeleteView` | `projects/confirm_delete.html` — takes its tasks off every list |
| `projects/<pk>/milestones/new/` | `MilestoneCreateView` | — POST from the timeline's inline form |
| `projects/<pk>/milestones/<id>/` | `MilestoneUpdateView` | `projects/milestone_form.html` |
| `projects/<pk>/milestones/<id>/toggle/` | `MilestoneToggleView` | — POST, done today / not done |
| `projects/<pk>/milestones/<id>/delete/` | `MilestoneDeleteView` | — POST; its tasks stay |
| `projects/<pk>/links/new/`, `…/links/<id>/delete/` | `LinkCreateView`, `LinkDeleteView` | — POST |
| `projects/<pk>/notes/new/`, `…/notes/<id>/delete/` | `NoteCreateView`, `NoteDeleteView` | — POST; delete is author-only |
| `projects/<pk>/budget/lines/new/`, `…/lines/<id>/delete/` | `BudgetLineCreateView`, `BudgetLineDeleteView` | — POST |
| `projects/<pk>/spending/` | `ProjectSpendingView` | `projects/spending.html` — suggestions, search, link (POST) |
| `projects/<pk>/spending/<id>/`, `…/<id>/delete/` | `ExpenseUpdateView`, `ExpenseDeleteView` | — POST: move to another line, or unlink |
| `projects/<pk>/tasks/new/` | `TaskCreateView` | `projects/task_form.html` — `?milestone=<id>` preselects |
| `projects/<pk>/tasks/<id>/edit/` | `TaskUpdateView` | `projects/task_form.html` |

Every child row is looked up scoped to its project, so an id from another
project is a 404.

## Upkeep

Everything here is behind the full gate, and — maintenance being shared
work — open to both members.

| Path | View | Template |
|---|---|---|
| `upkeep/` | `UpkeepListView` | `upkeep/list.html` — overdue and next 30 days, then by area |
| `upkeep/new/` | `UpkeepCreateView` | `upkeep/form.html` — the chore form (`household_only`) and the item form, saved together |
| `upkeep/<pk>/` | `UpkeepDetailView` | `upkeep/detail.html` — now, mark done with cost and note, how, supplies, history, spend by year |
| `upkeep/<pk>/edit/` | `UpkeepUpdateView` | `upkeep/form.html` |
| `upkeep/<pk>/jobs/<id>/purchase/` | `JobLinkView` | `upkeep/link.html` — link (or unlink) the purchase behind a done job |
| `upkeep/<pk>/delete/` | `UpkeepDeleteView` | `upkeep/confirm_delete.html` — deletes the chore and its history too |
| `upkeep/starter/` | `LibraryView` | `upkeep/library.html` |
| `upkeep/starter/<key>/` | `LibraryAdoptView` | — POST, adopts one starter entry |

`chores/<pk>/`, `chores/<pk>/edit/`, and `chores/<pk>/delete/` redirect to
these for a maintenance chore.

## Shared templates

| Template | Used for |
|---|---|
| `base.html` | Page chrome for every private page, finance included |
| `base_auth.html` | The signed-out screens: sign-in, 403, lockout |
| `403.html` | The one 403 for `/household` and `/finance` |
| `lockout.html` | Shown by django-axes after repeated failed sign-ins |
| `partials/header.html` | Brand, section links, account menu |
| `partials/nav_bottom.html` | The phone's section tab bar |
| `partials/section_nav.html` | A section's own screens as a pill strip |
| `partials/messages.html` | Flash messages |
| `partials/field.html` | One labelled form field with help text and error |
| `chores/_schedule_fields.html` | The schedule half of a chore form, with its live preview — shared by chores and maintenance |
