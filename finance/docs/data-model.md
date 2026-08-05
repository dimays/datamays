# Data model

Models live in `finance/models/`, one module per domain, re-exported from
`models/__init__.py` so callers write `from finance.models import Account`
regardless of which module a model lives in.

Every model inherits `TimestampedModel` (`created_at`, `updated_at`).

## Accounts and where data comes from

```
Institution ──< AccountConnection ──< Account ──< AccountBalanceSnapshot
     │                                  │
     └──────────────────────────────────┘
```

| Model | Purpose |
|---|---|
| `Institution` | A bank, brokerage or lender. Needed even for manual accounts, because a CSV import has to attach to one. |
| `AccountConnection` | One authenticated link to a provider. Holds the **encrypted** access secret, status, `last_synced_at`. One connection can cover several institutions — that is how SimpleFIN Bridge works. |
| `Account` | A single account. `connection` is **nullable**: that is what makes manual accounts (the mortgage, a 401(k)) possible. |
| `AccountBalanceSnapshot` | A dated balance reading. **Every balance chart is built from these**, not from summing transactions — which is impossible for accounts that only ever report a balance. |

Key `Account` fields:

- `account_type` — checking / savings / money market / credit card / student
  loan / mortgage / auto loan / investment / retirement / insurance / other
- `debt_reported_positive` — the one escape hatch for an institution that
  signs liabilities backwards. See [ADR 0003](../../docs/architecture/decisions/0003-household-sign-convention.md).
- `include_in_net_worth`, `include_in_spending` — exclude an account whose
  activity would double-count.

## Transactions and categories

```
Transaction >── Category ──< Category (self-FK, max 3 deep)
                   │  │
                   │  └──< CategoryRule
                   └─────< MerchantCategoryMemo
```

| Model | Purpose |
|---|---|
| `Transaction` | Idempotent on `(account, provider_txn_id)` plus a fingerprint fallback, so re-syncing never duplicates. Carries `category_source` ∈ {rule, memo, llm, manual}, `category_confidence`, `needs_review`, and transfer pairing. |
| `Category` | A tree, capped at `MAX_CATEGORY_DEPTH` (3). `kind` ∈ expense / income / transfer. |
| `CategoryRule` | Deterministic pattern → category. contains / starts-with / exact / regex, optionally scoped to one account or an amount range. |
| `MerchantCategoryMemo` | A normalized merchant string that has been confirmed before. This is what keeps the OpenAI bill near zero. |

### Deletion behavior — know this before deleting a category

| FK | `on_delete` | Consequence |
|---|---|---|
| `Category.parent` | `PROTECT` | A category with children cannot be deleted |
| `CategoryRule.category` | `CASCADE` | Deleting a category deletes its rules |
| `MerchantCategoryMemo.category` | `CASCADE` | …and its remembered merchants |
| `Transaction.category` | `SET_NULL` | …and **silently unfiles every transaction under it** |

That last one is why `CategoryDeleteView` makes you choose a category to
reassign to first, defaulting to Uncategorized.

### Load-bearing slugs

Three category slugs are referenced directly in code and marked `is_system`,
so the admin and the UI refuse to delete them:

- `uncategorized`
- `transfer-internal`
- `transfer-card-payment`

The tree is seeded from `categories_seed.py` via
`manage.py seed_finance_categories`. Safe to re-run: it matches on slug and
never deletes.

### Category ordering

Dropdowns use `Category.objects.alphabetical()`, **not** the model's default
`Meta.ordering`. The default groups by `sort_order` to match the seed's
nested-tree insertion order, which is right for a tree and wrong for a flat
dropdown.

## Budgets

```
Budget ──< BudgetPeriod
   ├──── categories (M2M)
   └──── accounts (M2M)
```

| Model | Purpose |
|---|---|
| `Budget` | An amount, a period type, and an **anchor date**. Budgets are anchored, not calendar-locked — a grocery budget can reset on payday. |
| `BudgetPeriod` | Materialized target-vs-actual for one budget in one window. Computed by rollup, not on page load, so the homepage is a read. |

Period arithmetic lives in `finance/periods.py` as **pure functions with no
database access**, which is what makes the edge cases — day-31 anchors, leap
years, month boundaries — cheap to test exhaustively.

## Income

| Model | Purpose |
|---|---|
| `Paycheck` | Gross → net for one pay period, optionally linked to the deposit `Transaction`. |
| `PaycheckDeduction` | One line: tax, retirement, HSA, insurance. Retirement and HSA are tracked as `RETAINED_KINDS` because **that money is still the household's** — treating it as lost the way tax is would understate what they earn. |

Payslips are optional. `net_income_over_time()` counts every income-categorized
deposit whether or not a payslip exists, so the Income view works for someone
whose pay never gets an itemized import.

## Imports

```
ImportBatch ──< ImportRow
     └──── ImportMapping (saved per institution + record type)
```

Three record types, fixed in `services/importer.py` rather than
user-configurable: transactions, balances, paycheck. The
`/imports/schemas/` screen exists to make that fixed shape *visible*.

## Alerts, reports, preferences, QFRs

| Model | Purpose |
|---|---|
| `Alert` | Four kinds: account-balance, budget-percent, budget-amount, source-staleness. **Personal** — scoped to one user. |
| `AlertEvent` | A firing, used for the cooldown check. |
| `ScheduledReport` | Weekly/monthly email digest. Personal. |
| `UserPreference` | Homepage widgets, chart sections, dashboard filters, all per-person. One-to-one with user. |
| `QuarterlyReport` | A QFR. Metrics and comparisons are **computed once at generation time and stored**, not recomputed on view — a report should read the same a year later even if categories have since changed. |
| `SyncRun` | Per-run observability: counts, duration, errors. |

Anything personal must go through `PersonalObjectMixin` in its views. See
[`architecture.md`](architecture.md).
