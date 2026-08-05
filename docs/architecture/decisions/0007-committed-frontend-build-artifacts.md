# 0007 — The built CSS and JS are committed

**Status:** accepted, with a known sharp edge
**Reverse cost:** low, but requires changing the Heroku buildpack setup

## Context

Tailwind compiles `assets/css/input.css` into `static/css/tailwind.css`. htmx,
Alpine and Chart.js are vendored into `static/js/`.

**Heroku runs no Node for this app.** There is no build step on deploy that
could produce these.

## Decision

`static/css/tailwind.css` and `static/js/*.min.js` are committed build
artifacts. After changing templates or bumping a frontend package, re-run the
build and commit the result:

```bash
npm run tailwind:build
```

```bash
npm run vendor:js
```

## The sharp edge

Tailwind only emits classes it has *seen* in the content it scans. A template
that starts using a utility class Tailwind has never encountered will render
**unstyled in production** if the build was not re-run — and everything will
look fine locally if your local CSS happens to be current.

This is a silent failure. There is no error, just a page that looks wrong.

Mitigations:

- `finance/tests/test_ui_conventions.py` asserts the committed CSS contains
  the app's component classes, which catches the common version of this.
- The PR checklist in [`../../conventions.md`](../../conventions.md) includes
  the build.

Neither catches every case. **Run the build after touching templates.**

## Why not build on deploy

Adding the Node buildpack would work and would remove the sharp edge. It also
adds a build step, a second language runtime in the slug, and a class of
deploy failure that does not currently exist. For a two-user app deploying a
few times a week, committing the artifact has been the cheaper trade — but
this is the ADR most likely to be revisited if the sharp edge ever causes a
real incident.
