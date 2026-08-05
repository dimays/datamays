# Architecture decisions

One file per decision that is expensive to reverse, or surprising enough on
first contact that someone would otherwise "fix" it back.

These are not a log of everything ever decided. A decision earns a file here
if reversing it would be costly, or if the obvious alternative looks better
until you know why it was rejected.

| # | Decision | Short version |
|---|---|---|
| [0001](0001-no-stored-bank-credentials.md) | Never store bank credentials | Read-only SimpleFIN tokens, revocable, that cannot move money |
| [0002](0002-money-is-decimal.md) | Money is `Decimal` | Floats can't represent 0.10; budgets that drift are worse than useless |
| [0003](0003-household-sign-convention.md) | One sign convention | Out is negative everywhere, so balances sum to net worth |
| [0004](0004-household-today-not-utc.md) | "Today" is Chicago, not UTC | UTC rolls over mid-evening and moved spending into the wrong day |
| [0005](0005-llm-is-the-last-resort.md) | The classifier runs last | Rules and remembered merchants first; keeps cost near zero and results stable |
| [0006](0006-heroku-scheduler-not-prefect.md) | Heroku Scheduler, not Prefect | Two cron entries beat an orchestrator for a two-user app |
| [0007](0007-committed-frontend-build-artifacts.md) | Commit the built CSS and JS | Heroku runs no Node |
