# Mays Household — architecture

How the shell is put together, and the rules that keep household and finance
from tangling. The *why* behind the two biggest calls is in
[ADR 0008](../../docs/architecture/decisions/0008-household-shell-owns-sign-in.md)
(the shell owns sign-in) and
[ADR 0009](../../docs/architecture/decisions/0009-one-household-app-one-finance-bridge.md)
(one app, one bridge to finance).

## The shell and its sections

```
household/                       the shell, plus (in later phases) chores,
                                 projects, and maintenance
  access.py         the three-gate access check every private page uses
  dates.py          household_today() — "today" in Chicago, not UTC
  redirects.py      safe_next(): the one validator for caller-supplied `next`
  forms/            StyledFormMixin and field classes; the sign-in forms
  views/base.py     PageTitleMixin, HouseholdView
  views/auth.py     sign-in, authenticator setup, second-factor challenge
  views/today.py    the Today screen
  integrations/finance.py   the only door into finance
  templatetags/household_nav.py   the section list
  templates/household/   base.html (page chrome), auth screens, 403, Today

finance/                         a section: extends household/base.html and
                                 adds its own section nav
```

## Dependency rules

Enforced by `tests/test_boundaries.py`, which parses every module's imports:

- **finance → household:** only the shell modules — `access`, `dates`,
  `redirects`, `forms.base`, `views.base`. Finance never learns chores or
  projects exist.
- **household → finance:** only `integrations/finance.py`, and it only reads.
  Linking household records to finance rows (a transaction to a project) is
  done with household-side rows; finance tables are never altered.
- Tests are exempt on both sides, and so is `services/demo.py`, the local
  demo seed.

If you need something new from finance, add a function to the bridge module
rather than importing finance where you are.

## Sign-in and the access gate

Three gates, in order, on every private page in every section
(`HouseholdAccessMixin`):

1. Authenticated?
2. A member of the `household` group?
3. Cleared the TOTP second factor in this session?

Failing 1 or 2 renders `household/403.html` with status 403 — **never a
redirect to the login page**, so a stranger learns nothing about what is
here. Failing 3 redirects to the second-factor screen, carrying the requested
page as `?next=` so signing in from a bookmark lands on the bookmark.

`tests/test_access.py::EveryRouteIsGatedTests` walks the URL resolver and
asserts every named route in both apps refuses a stranger and a signed-in
outsider. Adding a view that forgets the gate fails that test without anyone
having to add the view to a list. (It found one bug on its first run: the
authenticator setup screen returned a 500, not a 403, to an anonymous visitor.)

**Never look anything up before the gate.** The gate runs in `dispatch()`.
A view that fetches its object in `dispatch()` or `setup()` ahead of it —
or a mixin placed left of the gate in the bases — answers a stranger
differently for a real id (a redirect, a 403) than a missing one (a 404),
which tells them what exists. Fetch lazily (`get_object()`, a
`cached_property`) and put redirecting mixins after `HouseholdPageMixin`.
This happened twice while building maintenance; both are pinned by tests in
`tests/test_maintenance.py`.

The group was called `finance` before the shell existed.
`migrations/0001_rename_member_group.py` renames it in place on deploy, so
both members keep their access, passwords, and authenticators. It merges
rather than fails if a `household` group already exists.

## Page chrome and navigation

`household/base.html` is the one base template. It renders the header, the
phone's bottom tab bar, and a `section_nav` block above the page content.

Two levels of navigation:

- **Sections** — Today, Finance, and (as they are built) Chores, Projects,
  Upkeep — in the desktop header and the phone's tab bar, from
  `templatetags/household_nav.py::SECTIONS`. A section joins the list in the
  phase that builds it, never before; a link to a section that does not exist
  would be a dead end on a phone.
- **Badges** — a section can show a count on its nav item; Chores shows
  your overdue count (yours and shared), worked out once per request.
- **Section nav** — a section's own screens as a strip of pills, via
  `partials/section_nav.html`, the `.section-nav` component class in
  `assets/css/input.css`. On a phone it scrolls sideways with a faded right
  edge, and centers the current pill on load.

## Today

`views/today.py`, built from `services/checklist.py::today_summary` — the
same rows and buckets as the checklist, so the two can never disagree about
what is overdue. Overdue first, then today, then the coming week's
easy-to-forget chores, then finance's own budget widget (the same builder
and template as the finance homepage, through
`integrations/finance.py::budget_glance`). [screens.md](screens.md#today)
has the details.

Both Today and the checklist load every chore with its open occurrence in
two queries and apply the missed-occurrence collapse on read
(`occurrences.refresh`), so neither depends on the scheduler having run.
Query counts are tested flat as chores are added.

## Confirmation dialog

`household/base.html` holds one `<dialog>` and a few lines of script that
route every `hx-confirm` through it, in place of the browser's native
`confirm()` — which draws a light system box over this dark app. It is used
when marking someone else's chore done ([permissions.md](permissions.md)).

## Privacy

Sentry's `before_send` hook (`datamays/settings.py::_scrub_finance_data`)
strips request and user data from any error under `/finance` *or*
`/household`. Project budgets and linked transactions make the household side
exactly as private as finance.
