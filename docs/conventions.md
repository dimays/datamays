# Conventions

What the code expects of you. Most of these exist because breaking them cost
something once.

## Language

**US spelling, everywhere** — user-facing text, comments, docstrings, and
identifiers. Write `normalize_balance()`, not the `-ise` form.

This is enforced by `finance/tests/test_spelling.py`, which scans every
`.py`/`.html`/`.js`/`.md` file in the repo. It exists because US spelling was
asked for three separate times and each mechanical pass left instances behind
— including, on the last pass, three function names.

If a British spelling is genuinely required — quoting an external source, or
showing the wrong form as a counter-example — put `spelling-check: ignore` on
that line. Opt the line out; don't weaken the check.

## Money

**Money is `Decimal`, never `float`.** A binary float cannot represent 0.10
exactly, and a budget that drifts by a cent a month is worse than useless.
`money_field()` in `finance/models/base.py` is the only way a money column
gets defined.

`float()` is acceptable at exactly one boundary: serializing a number into
JSON for a chart, where it will be read and never written back. If you are
about to `float()` a value that will be stored or compared again, don't.

See [ADR 0002](architecture/decisions/0002-money-is-decimal.md).

## Signs

**Money leaving is negative, money arriving is positive** — on every account
type including credit cards. Balances follow the same rule: assets positive,
liabilities negative, so a set of balances sums to net worth with no
special-casing.

Normalizing into this convention is the provider adapter's job, at the
boundary. Reporting code never guesses.

See [ADR 0003](architecture/decisions/0003-household-sign-convention.md).

## Dates

**Every date decision goes through `finance/dates.py`**, never
`django.utils.timezone.localdate()`. The project's `TIME_ZONE` is UTC —
correct for storage and for the public site, wrong for a household budget,
because UTC has already rolled over to tomorrow by early evening in Chicago.

Use `household_today()`.

See [ADR 0004](architecture/decisions/0004-household-today-not-utc.md).

## Where code goes

| Kind of thing | Where |
|---|---|
| Business logic, arithmetic, anything worth testing without a request | `finance/services/` |
| Forms | `finance/forms/`, one module per subject — never inside a view module |
| Views | `finance/views/`, one module per screen area |
| Anything scheduled or run by hand | `finance/management/commands/`, as a thin wrapper around a service |
| Repeated UI class strings | `assets/css/input.css`, as an `@layer components` class |

Views stay thin. If a view is doing arithmetic, that arithmetic belongs in
`services/` where it can be tested without rendering anything.

## Forms

Do not write `attrs={"class": ...}` on a widget. `StyledFormMixin`
(`finance/forms/base.py`) applies the app's field styling by widget type.
Declare `widgets` only for attributes genuinely specific to the field — a
`step`, a `min`/`max`, a `rows`, a `placeholder`, `type="date"`.

## Views

Set `page_title` as a class attribute, or override `get_page_title()` when it
depends on the object. Do not write a `get_context_data` override whose whole
body is setting one string — `PageTitleMixin` handles it.

For anything personal to one household member (alerts, scheduled reports):

- `PersonalQuerysetMixin` scopes the queryset. **Every** personal view needs
  it, including deletes.
- `PersonalObjectMixin` adds the owner stamp on create. Only for views that
  write a new row.

They are separate because a `DeleteView` is confirmed with a plain `Form`
that has no `.instance` — a single mixin doing both turned every alert
delete into a 500, and no test noticed until one was written.

## Queries

**A page's query count must not grow with the number of accounts,
categories, or transactions.** It may grow with the number of *sections* on
it — that's a fixed cost you can read in the code.

`finance/tests/test_query_budgets.py` enforces both halves: a loose ceiling
per page, and a direct assertion that Charts costs the same with 4 accounts
as with 20.

The failure this protects against is quiet. Charts used to run one query per
account to find each one's opening balance, three times over — 71 queries at
9 accounts, 104 at 20 — and every test passed the whole time.

If you write a loop over accounts, budgets, or categories, ask what happens
inside it. `select_related` / `prefetch_related` for traversals; one grouped
query and a dict for lookups.

## Testing

- **Always** `--settings=datamays.settings_test`. See
  [`onboarding.md`](onboarding.md) for why this is not optional.
- One test file per feature area (`test_budgets.py`, `test_qfr.py`), not per
  module. A test file usually covers a service plus the views and templates
  that expose it.
- Provider and LLM calls are always mocked or stubbed. No test should be able
  to reach a real institution, a real OpenAI endpoint, or a real mail server.
- Where there is a plausible off-by-one — period boundaries, date arithmetic,
  sign conventions — write the boundary cases explicitly. `test_periods.py`
  and `test_dates.py` are the standard to match.
- Network calls never run inside an open database transaction. There are
  tests that will catch a regression
  (`test_categorize.py::ClassifierIsolationTests`,
  `test_qfr.py::GenerateQFRTransactionIsolationTests`).

## Branching and shipping

Branch off `main` per change. Stack branches when changes touch the same
files — independent branches over a shared file produce the same conflict
repeatedly, once per branch.

Before opening a PR:

```bash
uv run python manage.py test finance --settings=datamays.settings_test
```

```bash
uv run python manage.py makemigrations --check --dry-run --settings=datamays.settings_test
```

```bash
npm run tailwind:build
```

Merging to `main` triggers a Heroku deploy. Read
[`runbooks/deploy.md`](runbooks/deploy.md) before merging more than one PR at
a time — there is a race worth knowing about.

## Comments

The codebase's house style is to explain **why**, not what. A comment that
restates the line below it is noise; a comment recording why an obvious
approach was rejected is the most valuable thing in the file. Match the
density of the surrounding code.
