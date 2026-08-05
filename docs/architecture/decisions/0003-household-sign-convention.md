# 0003 — One sign convention, applied at the boundary

**Status:** accepted
**Reverse cost:** high — every aggregate and every chart assumes it

## Context

Institutions disagree about signs. A credit card might report a $500 balance
as `500` ("you owe this") or `-500` ("your balance is negative"). A payment
might arrive as a positive number on one feed and a negative on another.

Left unresolved, every piece of reporting code has to know which institution a
row came from before it can interpret the number.

## Decision

**From the household's point of view: money leaving is negative, money
arriving is positive.** On every account type, including credit cards.

Balances follow the same rule — assets positive, liabilities negative — so a
set of balances **sums directly to net worth** with no special-casing
anywhere.

Normalizing into this convention is the **provider adapter's job, at the
boundary** (`services/sync.py::normalize_balance`). Reporting code never
guesses and never inspects the institution.

## Consequences

- Net worth is a `SUM`. Not a sum with a sign flip per account type.
- Presentation is a separate concern: `Account.display_balance` and the
  `abs_money` / `money` template filters render a debt as a positive "amount
  owed", because that is how people read it. The *stored* number stays signed.
- Institutions that get it backwards are handled by one per-account flag,
  `debt_reported_positive` — a checkbox in Settings, not a code change and not
  edited data.
- Flipping that flag applies the sign change immediately rather than waiting
  for the next sync, because the next sync for a manual account may be never.

## Why not store what the institution sent

Because then "what is our net worth" is not a query — it is a query plus a
per-account lookup table plus the risk that a new institution has a convention
nobody has encoded yet. Normalizing once, at the edge, is the cheap place to
put the complexity.
