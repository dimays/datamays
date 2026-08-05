# Household Finance — architecture

Orientation for a developer touching this codebase, not this app's operator.
For "how do I run this in production," see [`runbook.md`](runbook.md). For
what each screen does, see the in-app Help page (header menu → Help).

This file covers layout and the conventions specific to this app. Its
siblings go deeper: [`data-model.md`](data-model.md),
[`pipeline.md`](pipeline.md), [`screens.md`](screens.md), and
[`extending.md`](extending.md) for step-by-step recipes. Repo-wide material —
dev setup, code conventions, deploys — is in [`../../docs/`](../../docs/).

## Layout

One Django app, `finance/`, split so no single file becomes a dumping ground:

```
finance/
  models/          One module per domain: accounts, transactions, categories,
                    budgets, imports, income, institutions, prefs, qfr.
                    Re-exported from models/__init__.py so callers still do
                    `from finance.models import Account`.
  providers/        The adapter interface (base.py) plus one adapter per
                    source. Adding a second provider means writing one
                    adapter here, not touching the sync service.
  services/         Where the actual logic lives: sync, categorize, rollups,
                    analytics, alerts, reports, qfr, importer, detection,
                    merchants, classifier. Views stay thin and call these.
  management/commands/  Every scheduled or backfill operation. Each is a
                    thin wrapper around a services/ function.
  templates/finance/     One subdirectory per screen area.
  tests/             One file per feature area, not per module — a test file
                    usually covers a service plus the views and templates
                    that expose it.
```

Views live in a `views/` package, one module per screen area, re-exported
from `views/__init__.py` — check `finance/urls.py` for the full map from URL
to view. `views/base.py` holds the three things every view shares: the access
gate, `PageTitleMixin` (set `page_title`, or override `get_page_title()` when
it depends on the object), and the personal-object mixins for the alert and
report views, which must only ever see the signed-in person's own rows —
`PersonalQuerysetMixin` to scope, `PersonalObjectMixin` to also stamp the
owner on create.

Forms live in `forms/`, not alongside the views that render them.
`forms/base.py`'s `StyledFormMixin` applies the app's field styling by widget
type, so a form declares `widgets` only for attributes specific to it — a
step, a min/max, a placeholder. Do not restate the class string.

## Two conventions everything depends on

Both are documented in [`models/base.py`](../models/base.py), and almost every
calculation in the app assumes they hold:

**Money is `Decimal`, never `float`.** A binary float can't represent 0.10
exactly, and a budget that drifts by a cent a month is worse than useless.
`money_field()` is the only way a money column gets defined. If you find
yourself writing `float(x)` on a value that will be stored or compared again,
stop — see `services/alerts.py`'s `observed_value` for the one place a float
round-trip actually mattered and was fixed.

**Signs are from the household's point of view.** Money leaving is negative,
money arriving is positive, on every account type including credit cards.
Balances follow the same rule: assets positive, liabilities negative, so a
set of balances sums directly to net worth with no special-casing anywhere.
Normalizing into this convention is the provider adapter's job at the
boundary (`services/sync.py::normalize_balance`); reporting code never
guesses. `Account.display_balance` and `abs_money`/`money` template filters
handle the presentation side — a debt should read as a positive "amount
owed," never as a signed figure.

## The data pipeline

Four stages, always in this order, because each depends on the one before:

```
sync → categorize → rollup budgets → evaluate alerts
```

- **Sync** (`services/sync.py`) pulls balances and transactions from a
  provider or a CSV import, upserting on a stable identity so re-running is
  always safe.
- **Categorize** (`services/categorize.py`) assigns a category, cheapest
  signal first: transfer detection → rules → remembered merchants → the LLM
  classifier, in that order. The classifier is the last resort, not the
  default — see the module docstring for why.
- **Rollup** (`services/rollups.py`) recomputes each budget's actual-vs-target
  for the current period from the transactions that now exist.
- **Alerts** (`services/alerts.py`) evaluate against the numbers rollup just
  produced.

This order is enforced by the two scheduled commands, `finance_hourly` and
`finance_daily` (`management/commands/`), which call the pipeline steps in
sequence and isolate failures — a broken sync still lets budgets roll up from
whatever data already exists, rather than aborting the whole run.

**Network calls never run inside an open database transaction.** The
classifier (OpenAI) and the QFR narrator (OpenAI) both make a call to a third
party; holding a transaction open across that call would pin a database
connection for as long as the provider takes to answer. `services/categorize.py`
and `services/qfr.py` both compute everything they can in Python first, then
make the one network call with nothing open, then write the result in a
single subsequent save. If you add a step that calls out to a network, follow
the same shape — there are tests
(`tests/test_categorize.py::ClassifierIsolationTests`,
`tests/test_qfr.py::GenerateQFRTransactionIsolationTests`) that will catch a
regression using `TransactionTestCase` and
`django.db.transaction.get_connection().in_atomic_block`.

## The provider abstraction

`providers/base.py` defines `ProviderAdapter`: one method, `fetch()`, that
returns normalized `AccountPayload`/`TransactionPayload` objects. `services/sync.py`
knows nothing about SimpleFIN specifically — it only knows the adapter
interface. Adding a second automated source means writing a new adapter and
registering it in `providers/registry.py`; nothing else changes.

CSV import (`services/importer.py`, `services/detection.py`) is a parallel
path for sources no adapter reaches — it produces the same `Transaction`
and `AccountBalanceSnapshot` rows sync does, just from a human-confirmed
column mapping instead of a live API.

## Categories

A tree, capped at three levels deep (`MAX_CATEGORY_DEPTH` in
`models/categories.py`), seeded from `categories_seed.py` and synced by
`manage.py seed_finance_categories`. A handful of slugs are load-bearing —
`uncategorized`, `transfer-internal`, `transfer-card-payment` — referenced
directly in code and marked `is_system` so the admin refuses to delete them.

Dropdowns populate via `Category.objects.alphabetical()`
(`models/categories.py`), not the model's default `Meta.ordering`. The default
groups by `sort_order` to match the seed's nested-tree insertion order, which
is wrong for a flat dropdown — see that method's docstring for the
parent-vs-child sorting rule.

## Budget periods and quarters

Budgets are anchored, not calendar-locked — a grocery budget can reset on
payday. `periods.py` holds this arithmetic as pure functions with no database
access, which is what makes the edge cases (day-31 anchors, leap years, month
boundaries) cheap to test exhaustively.

QFRs use *calendar* quarters unconditionally (`periods.py::quarter_bounds`),
deliberately not anchored the way budgets are — "Q1" has to mean the same
thing to both of you, always.

**Every date decision in this app goes through `finance/dates.py`, never
`django.utils.timezone.localdate()` directly.** The project's `TIME_ZONE` is
UTC, correct for storage and for the public site, wrong for a household budget
— UTC has already rolled over to tomorrow by around 7pm in Chicago. This bit
the app once (see the git history around `finance/dates.py`'s introduction)
and every date-sensitive call site was migrated off `timezone.localdate()`.
If you add one, use `household_today()`.

## Alerts

One model, `Alert`, four kinds (`AlertKind` in `models/prefs.py`):
account-balance, budget-percent, budget-amount, and source-staleness. Adding a
fifth kind means: a case in `services/alerts.py::observed_value()`, a case in
`build_message()`, and a validation branch in `Alert.clean()` if the new kind
needs its own required fields. `is_breached()` and the cooldown logic are
generic across all kinds — a new kind should not need to touch either.

## QFRs

`services/qfr.py` mirrors the classifier's Narrator pattern
(`services/classifier.py`): a `QFRNarrator` base class, a `NullNarrator` for
when no API key is configured, and an `OpenAINarrator` for when one is. Tests
stub the base class directly rather than mocking OpenAI's client — see
`tests/test_qfr.py::_StubNarrator` for the pattern to follow when testing
anything that calls a narrator.

Metrics and comparisons are computed once at generation time and stored on
the `QuarterlyReport` row (`metrics`/`comparisons` JSON fields), not
recomputed on view — a report should read the same a year later even if
categories or budgets have since changed.

## Testing conventions

- Always run with `--settings=datamays.settings_test`. The repo's `.env`
  points `DATABASE_URL` at the deployed Postgres; the default settings would
  run tests against it.
- One test file per feature area (`tests/test_budgets.py`,
  `tests/test_qfr.py`, …), not per module.
- Provider and LLM calls are always mocked or stubbed. No test should be able
  to reach a real institution, a real OpenAI endpoint, or a real mail server.
- When adding logic with a plausible off-by-one (period boundaries, date
  arithmetic, sign conventions), write the boundary cases explicitly rather
  than trusting a single happy-path assertion — see `tests/test_periods.py`
  and `tests/test_dates.py` for the standard this app holds itself to.
