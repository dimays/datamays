# 0006 — Heroku Scheduler, not an orchestrator

**Status:** accepted
**Reverse cost:** low — deliberately

## Context

The finance app has a recurring pipeline: sync → categorize → roll up budgets
→ evaluate alerts. That shape invites an orchestrator — Prefect, Airflow, a
task queue with a beat scheduler.

## Decision

**Two Heroku Scheduler entries**, each invoking a Django management command:

| Frequency | Command | Does |
|---|---|---|
| Hourly | `finance_hourly` | sync day-to-day accounts → categorize → roll up budgets → evaluate alerts |
| Daily | `finance_daily` | sync everything incl. loans/mortgage → snapshot balances → roll up → send due reports |

Each pipeline step is also an independently runnable command. The composite
commands only sequence them.

## Why not Prefect

A DAG engine earns its keep with backfills, retries across many dependent
tasks, and a scheduling graph too complex to hold in your head. This pipeline
is four steps in a fixed order for two users. Prefect would add a service to
run, a UI to log into, and a dependency to upgrade, in exchange for
capabilities this workload does not use.

The tradeoff was made explicitly, not by default. Prefect is worth adopting
for the horror-movie project, where DAGs and backfills do earn their keep.

## Consequences

- **Sync logic stays framework-agnostic.** The commands are thin wrappers
  around `services/` functions, so an orchestrator can wrap them later without
  a rewrite. That is the whole reason the wrapping is thin.
- **Each chain isolates step failures.** A failed sync still lets budgets roll
  up from data already present, rather than aborting the run. Both chains exit
  non-zero if any step failed, so a broken run shows in `heroku logs` instead
  of passing silently.
- **Heroku Scheduler only offers 10-minute / hourly / daily.** Hence exactly
  two entries rather than a finer schedule.
- SimpleFIN allows roughly 24 requests a day, which is why the hourly job is
  restricted to accounts that actually move hourly.
- **QFR generation is deliberately not scheduled.** A quarterly report should
  reflect complete data, and only a person knows when a backfill is genuinely
  finished. It is a button and a command, run on purpose.
