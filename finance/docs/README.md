# Household Finance

A private finance tool for two people, mounted at `/finance`.

It exists so David and Maddie can navigate their finances, adjust their
budgeting strategy, monitor their financial health, prepare for financial
advisor conversations, and track spending, savings and net worth over time.

Primary use case is a phone, checking a budget before a large purchase.
Secondary is a desktop, prepping for an advisor meeting. Both shape the UI:
mobile-first, with the answer to "can we afford this?" reachable in one tap.

## The docs

| | |
|---|---|
| [`architecture.md`](architecture.md) | How the app is laid out and why. **Read this first if you are changing code.** |
| [`data-model.md`](data-model.md) | Every model, what it is for, and the relationships that matter |
| [`pipeline.md`](pipeline.md) | sync → categorize → rollup → alerts, in detail |
| [`screens.md`](screens.md) | Every URL, its view, and its template |
| [`extending.md`](extending.md) | Step-by-step for the five changes most likely to be asked for |
| [`runbook.md`](runbook.md) | Operating it: setup, scheduling, key rotation, and what to do when a sync goes wrong |

Repo-wide material — dev setup, conventions, deploys, architecture decisions —
lives in [`../../docs/`](../../docs/).

What each screen does *for a user* is documented in-app, under the header
menu's Help link. These docs are for developers.

## Orientation in one screen

```
finance/
  models/       One module per domain, re-exported from __init__
  forms/        One module per subject, styled by StyledFormMixin
  views/        One module per screen area, re-exported from __init__
  services/     Where the logic lives. Views call these.
  providers/    Adapter interface + one adapter per external source
  management/commands/   Scheduled and manual operations
  templates/finance/     One subdirectory per screen area
  tests/        One file per feature area
  docs/         You are here
```

Three things almost every calculation assumes:

1. **Money is `Decimal`**, never `float`.
2. **Money out is negative**, on every account type, so balances sum to net
   worth.
3. **"Today" is `household_today()`**, not UTC.

Each is an architecture decision with its own write-up — see
[`../../docs/architecture/decisions/`](../../docs/architecture/decisions/).

## Costs

| Item | Cost |
|---|---|
| SimpleFIN Bridge | $15/yr |
| OpenAI categorization | ~$0.10–0.50/mo |
| Heroku Scheduler | ~$1–2/mo in dyno seconds |
| Dyno + Postgres | no change — shares the existing app |

## Deliberately out of scope

Light/dark theming (the site is dark-only), SMS alerts (email only), multi-user
or multi-household support, and any generality that only pays off at a scale
two users will never reach.
