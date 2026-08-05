# Deploying

## How it works

Merging to `main` triggers a Heroku GitHub auto-deploy. There is no manual
step and no staging environment.

```bash
gh pr merge <N> --merge
```

The repo has a required-review ruleset. For a solo change you have reviewed
yourself, `--admin` bypasses it:

```bash
gh pr merge <N> --merge --admin
```

## Before you merge

```bash
uv run python manage.py test finance --settings=datamays.settings_test
```

```bash
uv run python manage.py makemigrations --check --dry-run --settings=datamays.settings_test
```

```bash
npm run tailwind:build
```

If the build changed `static/css/tailwind.css`, commit it. Heroku runs no
Node — see [ADR 0007](../architecture/decisions/0007-committed-frontend-build-artifacts.md).

## ⚠️ The auto-deploy race

**This has bitten this repo. Read it before merging several PRs at once.**

Heroku's GitHub integration starts a build per push. Merging several PRs in
quick succession starts several builds, and **they do not necessarily finish
in order**. An earlier commit's build can land *after* a later one, leaving
production running older code than `main`.

When merging a batch:

1. Merge one PR.
2. Wait for its release to appear before merging the next.
3. Confirm the release versions increase monotonically *and* that the last
   release corresponds to the last merge commit.

```bash
heroku releases --app datamays
```

## Verify what actually deployed

**A release number is not proof.** It says a build finished, not that the
build contains your change. Check the deployed content directly:

```bash
heroku run "grep -n 'some string from your change' path/to/file.py" --app datamays
```

For a template or CSS change, fetch the page and look for the markup or the
class. For a migration:

```bash
heroku run python manage.py showmigrations finance --app datamays
```

This is not paranoia — during one batch merge the release counter advanced
correctly while production was serving a commit from two merges earlier.

## Migrations

There is no automatic `migrate` on release. Run it after deploying a
migration:

```bash
heroku run python manage.py migrate --app datamays
```

Check first if you are unsure:

```bash
heroku run python manage.py showmigrations finance --app datamays
```

## Rolling back

```bash
heroku releases --app datamays
```

```bash
heroku rollback v<N> --app datamays
```

Rollback reverts **code, not data**. If the bad release ran a migration or a
data-mutating command, roll the code back first to stop the bleeding, then fix
the data deliberately — see [`incidents.md`](incidents.md).

## Scheduled jobs

Two Heroku Scheduler entries, and only two:

| Frequency | Command |
|---|---|
| Hourly | `python manage.py finance_hourly` |
| Daily (early-morning UTC) | `python manage.py finance_daily` |

Both exit non-zero if any step failed, so a broken run shows in
`heroku logs --app datamays`.
