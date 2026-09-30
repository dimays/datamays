# 0009 — One app for chores, maintenance, and projects; one bridge to finance

**Status:** accepted
**Reverse cost:** medium — splitting later means moving models between apps

## Context

Chores, maintenance, and projects look like three features, which suggests
three Django apps. They are not independent, though:

- A maintenance item produces chores.
- A project task *is* a chore — assigning it puts it on someone's checklist.
- All three share one scheduling engine and one permission model.

Separately, project budgets and maintenance costs need finance data, and the
Today screen shows finance's budget widget.

## Decision

**One `household` app** holds the shell and all three sections, organized
the way `finance` is — one module per domain under `models/`, `services/`,
`views/`, and `forms/`.

**Dependency direction is fixed and tested:**

- `finance` imports only `household.access`, `household.dates`, and the
  shell's templates. It never learns chores or projects exist.
- `household` reaches finance only through `household/integrations/finance.py`,
  and only to read — plus writing its *own* link rows that point at finance
  transactions. It never writes a finance model.
- The demo seed (`household/services/demo.py`) is the single exception: it
  exists to build finance data locally, and never runs outside SQLite.

A test parses every module's imports and fails on a violation.

## Why not three apps

Three apps would put app boundaries exactly where the coupling is tightest.
Every chore query touching a project or maintenance item would cross an app
boundary, and the shared scheduling engine would need a fourth app of its
own. For a two-user tool that is ceremony with no payoff.

## Why a single bridge module

Finance has conventions that every consumer must honor — `Decimal` money,
the household sign convention, materialized budget periods. Funneling every
read through one module means those rules are applied in one place, and a
finance refactor has exactly one household file to check.

## Consequences

- Finance tables are never altered for household features. Linking a
  transaction to a project is a household-side row.
- If one section ever needs to become its own app, the module-per-domain
  layout makes the move mechanical.
