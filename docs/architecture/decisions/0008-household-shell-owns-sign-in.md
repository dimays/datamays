# 0008 — A household shell owns sign-in; finance becomes a section

**Status:** accepted (implementation lands in the `household/shell` phase)
**Reverse cost:** medium — a group rename and moved URLs

## Context

The finance app is growing into a wider household app with chores, projects,
and maintenance. Today the finance app owns everything a second section would
need to share: the sign-in screens, the TOTP gate, the `finance` group that
defines "a member of the household", the base template, the navigation, and
`household_today()`.

Two obvious routes present themselves:

1. **Rename the `finance` app to `household`** and grow it.
2. **Give each new section its own sign-in** and link between them.

## Decision

A new `household` app is the **shell**. It owns sign-in, the access gate,
the member group, the base template, the top-level navigation, the Today
landing screen, and what "today" means. `finance` keeps everything else about
money and becomes one section inside that shell.

- The member group is renamed from `finance` to `household` by a data
  migration. Existing users keep their passwords and TOTP devices.
- Sign-in moves to `/household/login/`; the old finance paths redirect.
- **Finance URLs do not move.** Emailed reports and bookmarks point at
  `/finance/…` and keep working.
- The gate's posture is unchanged and extended to every `/household/` path:
  a stranger gets a 403, not a login redirect.
- `household_today()` moves to `household/dates.py`; `finance/dates.py`
  re-exports it so no finance call site changes. See
  [ADR 0004](0004-household-today-not-utc.md).

## Why not rename the finance app

Renaming a Django app rewrites table names, content types, permissions, and
migration history — on a live database holding real balances — to gain
nothing a shell does not also provide. The finance app's internal name is
invisible to both users.

## Why not separate sign-ins

Two users, one household. A second password and a second TOTP enrollment
would be friction with no security benefit: whoever can see the budget can
see the chore list.

## Consequences

- `finance` depends on `household` for the gate and dates; the reverse
  dependency is confined to one module (see [ADR 0009](0009-one-household-app-one-finance-bridge.md)).
- Sentry's scrubbing hook, which strips request data for `/finance`, must
  cover `/household` too — project budgets carry money.
- `LOGIN_URL` and `LOGIN_REDIRECT_URL` move to the household namespace, and
  a verified session lands on Today rather than the finance homepage.
