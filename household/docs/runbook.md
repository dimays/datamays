# Runbook

Operating Mays Household in production. Repo-wide deploy mechanics are in
[`docs/runbooks/deploy.md`](../../docs/runbooks/deploy.md); read its
auto-deploy race section before merging.

## Shipping it the first time

`feature/household` merges to `main` once, when every phase is reviewed.
That deploy:

1. **Runs migrations `household.0001`–`0007`.** `0001` renames the `finance`
   auth group to `household` in place — both members keep access,
   passwords, and authenticators. It merges rather than fails if a
   `household` group somehow exists. Nothing else touches existing data.
2. **Moves sign-in** to `/household/login/`. The old `/finance/login/` and
   `/finance/two-factor/` paths redirect, keeping `?next=`, so bookmarks
   and the password manager's saved URL keep working.
3. **Changes the landing page** after sign-in to Today.

Then, by hand, in the Heroku Scheduler dashboard:

| Replace | With |
|---|---|
| `python manage.py finance_hourly` | `python manage.py household_hourly` |
| `python manage.py finance_daily` | `python manage.py household_daily` |

Same frequencies. Until this is done, chores still roll forward on read and
nothing breaks — but digests won't send and misses aren't recorded for
chores nobody opens.

Verify:

```bash
heroku run python manage.py showmigrations household --app datamays
```

```bash
heroku run python manage.py household_hourly --app datamays
```

Then sign in on a phone and check Today.

## Configuration

| Variable | Purpose |
|---|---|
| `HOUSEHOLD_TIME_ZONE` | What "today" means for chores, budgets, and digests. Defaults to `America/Chicago`; the old `FINANCE_TIME_ZONE` is still read if set |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` / `DEFAULT_FROM_EMAIL` | Digest email, shared with finance's alerts and reports |

The digest's links are built from `REDIRECT_DOMAIN` in settings
(`https://www.datamays.com/` outside dev).

## The morning digest

Opt-in per person under **Household preferences**. The hourly run sends it
on the first run at or after 7am household time, once per household day.
A morning with nothing to report records the day and sends nothing.

**"I didn't get one."**

- Is it switched on? `HouseholdPreference.morning_digest` in the admin.
- Is the user still an active member of the `household` group? Only current
  members get one.
- Does the user have an email address? Without one it is skipped (logged).
- Did the hourly run fail? `heroku logs --app datamays --source app | grep -i "household_hourly\|digest"`.
- A failed send is **not** recorded as sent, so the next hour retries.
  `last_digest_on` is the household date of the last one that went out (or
  of the last empty morning).

## Chores that look stale

Every screen applies the missed-occurrence rule on read, so a stale chore on
screen means a bug, not a skipped job. `sweep_chores` records misses for
chores nobody opened; it runs hourly and daily. To run it by hand:

```bash
heroku run python manage.py sweep_chores --app datamays
```

## Never in production

`seed_household_demo` and `demo_totp_code` refuse to run against anything
but SQLite, and production is Postgres. They are for `settings_local` only.
