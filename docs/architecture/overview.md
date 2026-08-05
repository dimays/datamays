# Repository architecture

## What this is

[datamays.com](https://datamays.com) — a personal portfolio site with a
private household finance tool mounted inside it.

```
Django 6 · Tailwind 3 · Postgres · Heroku (gunicorn + whitenoise) · Sentry
Python deps via uv · frontend built with Node, committed as artifacts
```

## Three apps

| App | Size | Public? | What it does |
|---|---|---|---|
| `core` | ~530 LOC | Yes | Projects, writing, styleguide. The portfolio. |
| `contact` | ~100 LOC | Yes | One form, one model, sends an email. |
| `finance` | ~19k LOC | **No** | The household finance tool at `/finance`. |

`finance` is the overwhelming majority of the codebase and has its own
[documentation set](../../finance/docs/README.md). `core` and `contact` are
small enough to read directly.

## Project layout

```
datamays/            settings, root urls, wsgi/asgi
  settings.py        the real one — reads .env, initializes Sentry
  settings_test.py   in-memory SQLite, Sentry disabled. Use for every test run.
core/                public site
contact/             contact form
finance/             the finance app (see finance/docs/)
assets/css/input.css Tailwind source
static/              committed build output — css/, js/, img/
docs/                this folder
```

## How a request is served

Nothing unusual for Django, with one exception worth knowing:

1. `datamays/urls.py` routes `/finance/` to `finance.urls`.
2. Every finance view sits behind `FinanceAccessMixin`, which enforces three
   gates in order: authenticated → member of the `finance` group → cleared
   the TOTP second factor.
3. The first two failures raise `PermissionDenied` and render a 403. **This
   is deliberately not a redirect to a login page** — a stranger probing
   `/finance` should not learn that a login form exists, nor what it protects.
   The third failure *is* a redirect, because by then the visitor has proven
   they hold a household account.

## Security posture

`finance` holds real balances for two real people, which sets the bar for the
rest of the project:

- **`SECRET_KEY` hard-fails outside dev.** It signs session cookies; silently
  falling back to a literal placeholder would make sessions forgeable.
  `datamays/settings.py` refuses to start rather than boot insecure.
- **Sentry scrubs `/finance`.** `send_default_pii=True` is on for the public
  site; a `before_send` hook strips request data for finance paths so balances
  and descriptions never reach a third party.
- **Secure cookies and HSTS** are set outside dev.
- **No bank credentials are stored, ever.** See
  [ADR 0001](decisions/0001-no-stored-bank-credentials.md) — this is the most
  important decision in the repo.
- **Provider access tokens are encrypted at rest** with a Fernet key from
  `FIELD_ENCRYPTION_KEYS`, never committed.

## Deployment

One Heroku app, one dyno, one Postgres. `git push` to `main` triggers an
automatic build and deploy. Scheduled work runs through the Heroku Scheduler
add-on invoking Django management commands — see
[ADR 0006](decisions/0006-heroku-scheduler-not-prefect.md).

Read [`../runbooks/deploy.md`](../runbooks/deploy.md) before merging several
PRs at once; auto-deploy has a race that has bitten this repo.

## Frontend

Server-rendered Django templates, progressively enhanced:

- **htmx** for partial updates
- **Alpine.js** for local interactivity (dropdowns, selection state)
- **Chart.js** for the finance charts

All three are vendored into `static/js/` — no CDN, no runtime third party.
Tailwind is compiled from `assets/css/input.css` into `static/css/tailwind.css`
and committed, because Heroku runs no Node.

The site is dark-only by design. Theming is explicitly out of scope.
