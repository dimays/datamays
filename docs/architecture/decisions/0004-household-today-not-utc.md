# 0004 — "Today" is the household's day, not UTC

**Status:** accepted, and this one already bit us
**Reverse cost:** moderate, but the failure is silent

## Context

The project's `TIME_ZONE` is UTC. That is correct for storage and correct for
the public site.

It is wrong for a household budget. **UTC has already rolled over to tomorrow
by around 7pm in Chicago.** A transaction made on a Tuesday evening was
landing in Wednesday's bucket; a budget period that should have reset on the
1st reset on the last evening of the previous month.

Nothing errored. The numbers were just quietly wrong for a few hours a day.

## Decision

Every household date decision goes through **`household_today()`**, never
`django.utils.timezone.localdate()` directly.

```python
from household.dates import household_today

today = household_today()
```

The zone comes from `HOUSEHOLD_TIME_ZONE`, defaulting to `America/Chicago`.

**Amended 2026-09-30** ([ADR 0008](0008-household-shell-owns-sign-in.md)):
this began as `finance/dates.py` and `FINANCE_TIME_ZONE`. It moved to
`household/dates.py` when finance became one section of Mays Household, since
chores and maintenance need the same "today". `finance/dates.py` re-exports
it, and `FINANCE_TIME_ZONE` is still honored as a fallback.

## Consequences

- Storage stays UTC. This is only about what "today" and "this period" mean.
- Every date-sensitive call site was migrated when this was introduced. If you
  add a new one, use `household_today()`.
- Tests around period boundaries are written as explicit boundary cases —
  see `tests/test_dates.py` and `tests/test_periods.py`.

## Why not just set `TIME_ZONE`

Because it would move the public site too, and because storage genuinely
should be UTC. The household's day is a *domain* concept — it belongs to the
finance app, not to the project.
