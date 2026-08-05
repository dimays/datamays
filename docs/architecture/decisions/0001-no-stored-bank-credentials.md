# 0001 — Never store bank credentials

**Status:** accepted, load-bearing
**Reverse cost:** very high — this is the decision the whole data pipeline is shaped around

## Context

The app needs balances and transactions from six financial institutions. The
obvious approach, and the one originally proposed, was to store each
institution's username and password and replay them at sync time.

## Decision

**Bank usernames and passwords are never stored, anywhere, in any form.**

Data arrives one of two ways:

1. **SimpleFIN Bridge** (~$15/yr). You authorize each institution on
   SimpleFIN's own site and receive a single-use setup token. The app
   exchanges that token for a read-only Access URL, stores it encrypted, and
   uses it to pull. The URL can never move money and is revocable in one click
   from SimpleFIN.
2. **CSV import / manual entry**, for institutions no aggregator reaches.

## Why the obvious approach was rejected

Storing replayable credentials to real money:

- Puts a credential that *can move money* in a database, when read access is
  all that is needed.
- Breaks on every MFA challenge, which is most institutions, most of the time.
- Violates the terms of service of essentially every US bank.
- Likely voids fraud-liability protections, which generally assume credentials
  were not shared with a third party.

The last point is the decisive one. The downside is not "the sync breaks" —
it is "the bank declines to make you whole after fraud."

## Consequences

- **Two institutions cannot be automated by anyone.** Northwestern Mutual
  permanent-life cash value and CrossCountry Mortgage are not reliably covered
  by SimpleFIN, Plaid, MX, or Teller. Same for One Wealth portfolios and
  employer 401(k)s, which depend on the custodian. These use manual accounts
  with dated snapshots.
- **The Savings & Debt picture is partly manual-refresh by design.** It is not
  broken when it looks stale; it is waiting for a CSV or a typed balance.
- The provider abstraction (`finance/providers/`) exists so a second read-only
  aggregator can be added without touching the sync service.

## What would change this

Nothing short of a read-only aggregator with materially better institution
coverage. Even then, the "read-only, revocable, never a password" property is
non-negotiable.
