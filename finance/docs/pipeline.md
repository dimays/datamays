# The data pipeline

Four stages, always in this order, because each depends on the one before:

```
sync → categorize → roll up budgets → evaluate alerts
```

Getting the order wrong is not a crash — it is alerts firing on yesterday's
budget numbers, which is worse.

## 1. Sync — `services/sync.py`

Pulls balances and transactions from a provider or a CSV import and upserts
them on a stable identity, so re-running is always safe.

**Idempotency.** A transaction is identified by `(account, provider_txn_id)`
where the provider supplies one, and by a content fingerprint where it does
not. Re-running a sync immediately must not change the transaction count —
there is a test for exactly that.

### The deduplication rule

**Within one source, trust it. Across sources, deduplicate.**

A CSV file listing three identical $4.75 coffees is asserting three coffees
happened. A sync payload carrying three with distinct provider ids is
asserting the same. Neither gets second-guessed — collapsing them would
silently delete real spending.

Two exports covering the same week, or a CSV import the provider later
reports, are the same money described twice. Those collapse.

| Situation | Result |
|---|---|
| One file, three identical rows | 3 transactions |
| The same file imported twice | 3 transactions |
| Two files, one identical row each | 1 transaction |
| A file with one row, then a cumulative export with three | 3 transactions |
| One sync payload, three identical (distinct provider ids) | 3 transactions |
| A CSV row the provider later reports | 1 transaction |

Two mechanisms enforce it, and they must agree:

- The importer counts *occurrences* — the row's index within the file against
  how many matching rows already exist. A plain "does a match exist" check
  would drop the genuinely-new coffees in the cumulative-export case.
- The sync only claims rows with **no** `provider_txn_id`, which is exactly
  the CSV-imported case. A row another payload already claimed is invisible
  to it.

Both use `models.transactions.same_transaction()` for "is this the same
movement of money". They previously did not, and the gap created a duplicate
of every CSV-imported transaction the provider later reported — the sync had
no ledger check at all, and `next_fingerprint()` stepped past the fingerprint
collision that would otherwise have caught it.

Stated in tests as `test_csv_import.SourceOfTruthTests` and
`test_sync.SyncTrustsItsOwnPayloadTests`.

**Sign normalization** happens here, at the boundary
(`normalize_balance()`). Nothing downstream guesses. See
[ADR 0003](../../docs/architecture/decisions/0003-household-sign-convention.md).

**Balance snapshots** are written per sync, which is what makes the balance
and net-worth charts continuous rather than a scatter of dots.

Every run records a `SyncRun` with counts, duration and any error.

## 2. Categorize — `services/categorize.py`

Ordered, cheapest and most certain first:

| Step | Source | Confidence |
|---|---|---|
| 1 | **Transfer detection** — matched opposite amounts across your own accounts within a few days | — excluded from spend/income |
| 2 | **`CategoryRule`** — deterministic pattern, highest priority wins | `1.0` |
| 3 | **`MerchantCategoryMemo`** — merchant seen and confirmed before | high |
| 4 | **LLM classifier**, batched, for what's left | as reported |
| 5 | **Review queue** — anything below threshold | `needs_review=True` |

Confirming an item in the review queue writes a memo, so the same merchant is
never asked about twice. The queue should shrink toward empty rather than
becoming a chore.

Full reasoning in [ADR 0005](../../docs/architecture/decisions/0005-llm-is-the-last-resort.md).

**The classifier sometimes returns a category slug that does not exist.** The
pipeline discards those rather than trusting them; the transaction falls
through to review. This is expected behavior, not a bug to chase.

**Network calls never run inside an open database transaction.** Compute
everything possible in Python, make the one call with nothing open, then write
the result. `test_categorize.py::ClassifierIsolationTests` enforces this using
`TransactionTestCase` and `transaction.get_connection().in_atomic_block`.

## 3. Roll up budgets — `services/rollups.py`

Recomputes each budget's actual-vs-target for the current period from the
transactions that now exist, writing a `BudgetPeriod`.

Materialized rather than derived on page load, because the homepage shows
every active budget and a per-request recomputation would make the most-visited
screen the slowest.

`expand_categories()` is the shared definition of "what counts toward this
budget" — a budget on a parent category counts its children too. The activity
list uses the same function, so a budget click-through shows exactly the rows
behind the number.

## 4. Evaluate alerts — `services/alerts.py`

Runs against the numbers rollup just produced.

One model, four kinds. `is_breached()` and the cooldown logic are generic
across all kinds — adding a fifth should not need to touch either. See
[`extending.md`](extending.md).

## How it is scheduled

Two Heroku Scheduler entries, each a thin management command that sequences
the steps:

| Frequency | Command | Scope |
|---|---|---|
| Hourly | `finance_hourly` | sync **day-to-day accounts only** (checking, savings, money market, credit cards) → categorize → rollup → alerts |
| Daily | `finance_daily` | sync **everything** incl. loans and mortgage → snapshot balances → rollup → send due reports |

The hourly job is restricted to accounts that actually move hourly because
SimpleFIN allows roughly 24 requests a day.

**Both chains isolate step failures.** A failed sync still lets budgets roll up
from data already present, rather than aborting the run. Both exit non-zero if
any step failed, so a broken run surfaces in `heroku logs` instead of passing
silently.

Every step is also its own command, so any stage can be re-run alone:

```bash
heroku run python manage.py sync_accounts --app datamays
```

```bash
heroku run python manage.py categorize_transactions --app datamays
```

```bash
heroku run python manage.py rollup_budgets --backfill 12 --app datamays
```

## The parallel path: CSV import

`services/importer.py` and `services/detection.py` produce the **same**
`Transaction` and `AccountBalanceSnapshot` rows sync does — just from a
human-confirmed column mapping instead of a live API.

Upload → auto-detect columns → confirm the mapping → preview → commit. Nothing
is written until a person has looked at the proposed columns *and* the
resulting preview, because auto-detection is good enough to be right most of
the time and confident enough to be dangerous when it isn't.

A confirmed mapping is saved as an `ImportMapping` and replayed on the next
file from that institution.
