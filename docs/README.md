# datamays documentation

Start here. This folder documents the repository as a whole; each app has its
own `docs/` folder for anything specific to it.

## If you are…

**New to the repo** → [`onboarding.md`](onboarding.md). Setup, the one trap
that will bite you (the local `.env` points at production), and how to run
things.

**About to write code** → [`conventions.md`](conventions.md). Spelling, money,
dates, testing, and how changes get branched and shipped.

**Trying to understand the shape of it** →
[`architecture/overview.md`](architecture/overview.md). Three Django apps, what
each is for, and how a request gets served.

**Asking "why is it like this?"** →
[`architecture/decisions/`](architecture/decisions/). One file per decision
that is expensive to reverse or surprising on first contact — why bank
credentials are never stored, why money is `Decimal`, why "today" is not UTC.

**Shipping or fixing something in production** →
[`runbooks/deploy.md`](runbooks/deploy.md) and
[`runbooks/incidents.md`](runbooks/incidents.md).

## Per-app documentation

| App | Docs | What it is |
|---|---|---|
| `finance` | [`finance/docs/`](../finance/docs/) | Private household finance tool at `/finance`. By far the largest app; start with its [README](../finance/docs/README.md). |
| `core` | [`core/docs/`](../core/docs/) | The public site — projects, writing, styleguide. |
| `contact` | [`contact/docs/`](../contact/docs/) | The contact form. One model, one view. |

## A note on scope

The `finance` app exists to do one job: let David and Maddie navigate their
finances, adjust their budgeting, watch their financial health, prepare for
advisor conversations, and track spending, savings and net worth over time.

It has two users. It is not a product, and generality that only pays off at
a scale it will never reach is a cost, not an investment. Where these docs
record a decision to *not* build something, that is usually why.
