# Getting set up

## Read this first

**The repo's `.env` points `DATABASE_URL` at the deployed Heroku Postgres.**

That means the default settings — for `runserver`, for `manage.py test`, for a
`shell` — talk to **production data**. Running the test suite under default
settings asks the production database server to create a test database.

Every local command in these docs therefore passes
`--settings=datamays.settings_test`, which pins to in-memory SQLite and
disables Sentry. If you are about to run something that touches the ORM and
you have not thought about which database it will hit, stop and think about
it.

```bash
uv run python manage.py test --settings=datamays.settings_test
```

## Requirements

- Python 3.12, managed by [`uv`](https://docs.astral.sh/uv/)
- Node, only for building CSS and vendoring JS — never at runtime
- Docker + VS Code Dev Containers, optional but the supported path

## First run

```bash
git clone git@github.com:dimays/datamays.git
cd datamays
uv sync
npm install
```

In the dev container, `.devcontainer/post-create.sh` does both installs for you.

Then:

```bash
uv run python manage.py migrate --settings=datamays.settings_local
```

```bash
uv run python manage.py seed_household_demo --settings=datamays.settings_local
```

```bash
uv run python manage.py runserver --settings=datamays.settings_local
```

`settings_local` is for clicking around: a file-based SQLite database
(`db.local.sqlite3`, gitignored), console email, no Sentry, no LLM calls.
`seed_household_demo` fills it with a fictional household — two members,
four months of spending, budgets — and refuses to run against anything but
SQLite. Sign-in details are in [`household/docs/`](../household/docs/README.md).
Never run `runserver` under the default settings; it serves production data.

## The commands you will actually use

| Task | Command |
|---|---|
| Run the suite | `uv run python manage.py test --settings=datamays.settings_test` |
| One test file | `uv run python manage.py test finance.tests.test_budgets --settings=datamays.settings_test` |
| Check for model drift | `uv run python manage.py makemigrations --check --dry-run --settings=datamays.settings_test` |
| System checks | `uv run python manage.py check --settings=datamays.settings_test` |
| Rebuild CSS **(required after template edits)** | `npm run tailwind:build` |
| Re-vendor htmx/Alpine/Chart.js | `npm run vendor:js` |

## Build artifacts are committed

`static/css/tailwind.css` and `static/js/*.min.js` are checked in, because
**Heroku runs no Node**. A template that uses a class Tailwind has not seen
before will render unstyled in production unless the build was re-run and the
result committed.

`finance/tests/test_ui_conventions.py` fails if the committed CSS is missing a
component class, which catches the common version of this mistake — but it
cannot catch every unbuilt utility. After touching templates, run the build.

See [ADR 0007](architecture/decisions/0007-committed-frontend-build-artifacts.md)
for why it works this way.

## Getting into Mays Household locally

The private apps are gated three ways: authenticated, a member of the
`household` group, and cleared a TOTP second factor. The demo seed (above)
creates two members who already have an authenticator; sign in at
`/household/login/` as described in
[`household/docs/`](../household/docs/README.md).

To create an account by hand instead — you will be walked through enrolling an
authenticator app on first sign-in:

```bash
uv run python manage.py create_finance_user david --first-name David --email you@example.com --settings=datamays.settings_local
```

## Where to go next

- [`conventions.md`](conventions.md) — what the code expects of you
- [`architecture/overview.md`](architecture/overview.md) — how the pieces fit
- [`../finance/docs/README.md`](../finance/docs/README.md) — the finance app itself
