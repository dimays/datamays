# Runbook

Operating Mays Household in production. Repo-wide deploy mechanics are in
[`docs/runbooks/deploy.md`](../../docs/runbooks/deploy.md); read its
auto-deploy race section before merging.

## Shipping it the first time

`feature/household` merges to `main` once, when every phase is reviewed.

**Before merging**, check nobody unexpected is already in a `household`
group (the migration adds the members to it; anyone already there would gain
access):

```bash
heroku run "python manage.py shell -c \"from django.contrib.auth.models import Group; print(list(Group.objects.filter(name='household').values_list('user__username', flat=True)))\"" --app datamays
```

It should print `[]` (or nothing but your two usernames).

**The deploy then, in order:**

1. **Runs migrations in the release phase**, before the new code takes any
   traffic (`release:` in the `Procfile`). If a migration fails, the release
   fails and the old code keeps serving — nobody is locked out. Migrations
   `household.0001`–`0009` create the household tables and **add both
   members to a new `household` group, leaving the `finance` group as it
   was** (copied, not renamed — see *Rolling back*). Passwords and
   authenticators are untouched.
2. **Moves sign-in** to `/household/login/`. The old `/finance/login/` and
   `/finance/two-factor/` paths redirect, keeping `?next=`.
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
heroku releases --app datamays
```

(the newest release should show the release phase succeeded), then:

```bash
heroku run python manage.py showmigrations household --app datamays
```

```bash
heroku run python manage.py household_hourly --app datamays
```

Then sign in on a phone and check Today.

## Rolling back

`heroku rollback` restores code, not data. The migrations were written so
that is safe:

- The `finance` group was **copied** into `household`, not renamed, so the
  pre-household code still finds both members in the group it checks. (The
  first version renamed it; a rollback would have locked both of you out of
  your own finances. Found in pre-merge review.)
- The household tables stay behind, unused by the old code. Nothing in the
  old code touches them.

To roll back:

1. In Heroku Scheduler, switch the two entries **back** to
   `python manage.py finance_hourly` and `python manage.py finance_daily` —
   the old code has no `household_*` commands, so leaving them would
   silently stop finance's sync and alerts.
2. `heroku rollback v<N> --app datamays`.

**Only if you also want the household data gone:** while the household code
is still deployed — *before* step 2 — run:

```bash
heroku run python manage.py migrate household zero --app datamays
```

It drops the household tables and folds anyone in `household` back into
`finance`. It can't be run after the rollback: the old code has no
`household` app. Don't rename groups by hand instead; the migration records
would then disagree with the data.

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
- Was it sent already today? `last_digest_on` is claimed *before* sending
  (so overlapping runs can't both send) and released if the send fails.
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
