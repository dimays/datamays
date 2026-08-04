# Household Finance — runbook

Operating notes for the `finance` app. Written for the version of me that has
forgotten all of this in eight months.

## First-time setup

### 1. Generate and set the encryption key

Provider credentials are encrypted at rest with this key. **Lose it and every
connection has to be re-authorized** — the data survives, the credentials do not.

```bash
uv run python manage.py generate_encryption_key
```

```bash
heroku config:set FIELD_ENCRYPTION_KEYS="<the key>" --app datamays
```

Keep a copy somewhere you'd still have it if Heroku vanished — a password
manager, not this repo.

### 2. Confirm the other config vars

| Variable | Purpose | Required |
|---|---|---|
| `FIELD_ENCRYPTION_KEYS` | Encrypts provider credentials | Yes |
| `SECRET_KEY` | Signs sessions — the app refuses to boot without it outside dev | Yes |
| `OPENAI_API_KEY` | Transaction categorisation and QFR narratives | No — both degrade gracefully without it |
| `FINANCE_CATEGORISER_MODEL` | Defaults to `gpt-4o-mini` | No |
| `FINANCE_QFR_MODEL` | Defaults to `gpt-4o-mini` | No |
| `FINANCE_TIME_ZONE` | What "today" means for periods and alerts. Defaults to `America/Chicago` | No |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | Alerts and reports | Only if you want email |

### 3. Create the two accounts

```bash
heroku run python manage.py create_finance_user david --first-name David --email you@example.com --app datamays
```

Group membership in `finance` is what grants access. Each person enrols an
authenticator app on first sign-in.

### 4. Seed the categories

```bash
heroku run python manage.py seed_finance_categories --app datamays
```

Safe to re-run; it matches on slug and never deletes.

### 5. Connect the institutions

Authorize them at <https://bridge.simplefin.org/>, then paste the setup token
at **Settings → Connect an institution**. A single SimpleFIN Bridge setup can
link several institutions to one token — the app doesn't need a separate
token per institution, since each account is matched to its own institution
automatically from what SimpleFIN reports for it during sync. The app
exchanges the token, stores it encrypted, and pulls 90 days as a test.

Institutions SimpleFIN cannot reach — Northwestern Mutual, CrossCountry
Mortgage, One Wealth, employer 401(k)s — get a manual account and a CSV import
instead (**Settings → Imports**).

## Scheduling

Add the Heroku Scheduler add-on, then create exactly two jobs:

| Frequency | Command |
|---|---|
| Hourly | `python manage.py finance_hourly` |
| Daily (pick an early-morning UTC time) | `python manage.py finance_daily` |

**Hourly** syncs day-to-day accounts (checking, savings, money market, credit
cards), categorises what arrived, rolls up budgets, then evaluates alerts. The
order matters — alerts must see fresh budget numbers.

**Daily** syncs *everything* including loans and the mortgage, snapshots
balances so the history charts stay continuous, rolls up budgets, and sends any
due reports.

Both chains isolate each step: a failed sync still lets budgets roll up from
the data already present. Both exit non-zero if any step failed, so a broken
run shows up in `heroku logs` rather than passing silently.

SimpleFIN allows roughly 24 requests a day, which is why the hourly job is
restricted to accounts that actually move hourly.

## Quarterly Finance Reports

Not on the scheduler — a QFR should reflect complete data for its quarter, and
only you know when a backfill is genuinely finished. Generate by hand once a
quarter has closed:

```bash
# One quarter
heroku run python manage.py generate_qfrs --quarter 2026-Q2 --app datamays

# Every completed quarter from a starting point through the most recent
heroku run python manage.py generate_qfrs --since 2025-Q1 --app datamays
```

Idempotent by default — re-running leaves existing reports alone. Pass
`--regenerate` to recompute and overwrite (useful after importing more
history that should have counted toward an existing report).

A report generates with its metrics either way; the four narrative sections
are only written when `OPENAI_API_KEY` is set at generation time. Missing that
key is not a failure — the report page says plainly that no narrative was
generated, and the numbers are unaffected.

## When something looks wrong

**Balances look stale.** The homepage flags accounts that haven't refreshed in
three days. Check **Settings → Recent syncs**, then the connection's own page
for the provider's error. `needs_reauth` means the credential was rejected —
generate a fresh SimpleFIN token and reconnect.

```bash
heroku run python manage.py sync_accounts --connection <id> --manual --app datamays
```

**A liability shows the wrong sign.** Some institutions report a debt as
already-negative rather than as a positive amount owed. Untick
*"Most institutions report a debt as a positive amount owed"* on that account
in **Settings → Accounts**. Don't edit data to compensate.

**Transactions aren't categorised.** Check `OPENAI_API_KEY` is set. Without it
everything still runs — rules and remembered merchants apply — and the rest
queues in **Activity → needs review**. To re-run:

```bash
heroku run python manage.py categorize_transactions --app datamays
```

**A budget looks wrong after editing it.** Editing recomputes the current
period only. To rebuild history:

```bash
heroku run python manage.py rollup_budgets --backfill 12 --app datamays
```

**Alerts are too noisy.** Each alert has a cooldown (default 24h). Budget
alerts can also gate on how far through the period you are, which is how you
say "only tell me if we hit 80% before the 15th".

**A source-staleness alert won't fire, or fires when it shouldn't.** It
compares against the account's most recent activity — a connection's
`last_synced_at` if it has one, otherwise its newest balance snapshot. A
brand-new account with no snapshot yet gets one grace cycle rather than
firing immediately; give it a sync or an import first.

## Rotating the encryption key

Fernet supports multiple keys: the first encrypts, all of them decrypt.

1. Generate a new key.
2. Set `FIELD_ENCRYPTION_KEYS="<new>,<old>"` — new one first.
3. Re-save each connection so it re-encrypts under the new key (open and save
   it in the admin, or re-authorize).
4. Drop the old key: `FIELD_ENCRYPTION_KEYS="<new>"`.

Skipping step 3 means step 4 makes those credentials unreadable. Settings pages
still load in that state — deliberately, so you can get in and reconnect — but
syncing will fail until you do.

## Local development

Always use the test settings for the suite. The repo's `.env` points
`DATABASE_URL` at the deployed Postgres, so the default settings would run
tests against production:

```bash
uv run python manage.py test finance --settings=datamays.settings_test
```

After changing templates, rebuild the committed CSS — Heroku runs no Node:

```bash
npm run tailwind:build
```
