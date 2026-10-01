# The finance bridge

Where household records meet real money: project budgets against actual
spending, maintenance jobs tied to the purchase behind them, and what
upkeep is expected to cost. The rules are
[ADR 0009](../../docs/architecture/decisions/0009-one-household-app-one-finance-bridge.md);
this is how they play out.

## Reading finance: one module

`household/integrations/finance.py` is the only household module that
imports finance (tested). It offers:

| Function | For |
|---|---|
| `budget_glance(user)` | Finance's own budget widget, on Today |
| `spent(txn)`, `total_spent(txns)` | The **one place** a signed amount becomes "spent" |
| `get_transaction(pk)` | Validating a posted link — `None` for a missing or non-numeric id |
| `spending_candidates(start=, end=, query=, exclude_ids=)` | Purchases that could be linked |

**"Spent" is always `-amount`.** Finance stores money leaving as negative
(ADR 0003), so a $42.50 purchase spent 42.50 and a $10 refund spent -10.00,
netting back against the purchase it corrects. Nothing else in household
code flips a sign; candidate rows carry `txn.spent` so templates don't
either.

**Candidates use finance's definition of spend** (`spend_filter`): no
transfers, no income, refunds against expense categories included. A
project's "actual" can never count something finance's own reports
wouldn't. Without a search, only home categories are suggested
(`HOME_CATEGORY_SLUGS` — improvement, maintenance, furnishings, household
and general shopping); a merchant search reaches every category.

## Writing: household rows only

Finance's tables are never altered. Links are household rows pointing at
`finance.Transaction`:

| Row | Points at | When the transaction is deleted |
|---|---|---|
| `ProjectExpense` | project, optional budget line, transaction | the link goes too — it is no longer spending |
| `Occurrence.transaction` | the purchase behind a maintenance job | the link is cleared; the cost it set stays |

A transaction can count toward several projects but only once per project
(`one_link_per_project_transaction`).

## Project budgets

`services/spending.py::budget_summary` — two queries per project page.

- **Lines** (`BudgetLine`) are the plan: a label and an estimate.
- **Actual** is the sum of linked transactions' spend; per line, plus
  anything linked without a line ("Not on a line"). Line actuals plus
  unassigned always equal the total — tested to the cent.
- **Target** is the project's overall budget if set, otherwise the sum of
  the lines' estimates. "Over" and "left" are measured against it.
- Removing a line keeps its spending on the project, unassigned.

The **Link spending** page suggests home spending from a month before the
project started through today, excluding what's already linked; searching
looks a further year back.

## Maintenance purchases

A done job's history row offers **Link the purchase**: home spending within
two weeks of the day it was done (or a search across the previous three
months). Linking sets the job's cost from the transaction — the purchase is
the truth — unless it was a refund, which can't be a job's cost. Unlinking
keeps the cost as the best figure there is.

## Upcoming maintenance costs

`services/spending.py::projected_costs` — the Upkeep page shows the next 90
days and the next 12 months. For each active item **with a usual cost**:
the current occurrence counts once if due inside the window (overdue
included — it'll be done soon), then every later due date: the fixed
schedule's dates, or for an after-completion schedule, one interval at a
time assuming each is done when due. Items without a usual cost are left
out rather than guessed at.
