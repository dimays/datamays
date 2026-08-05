# core

The public site: projects, writing, and the styleguide.

About 530 lines across `models.py`, `views.py` and `urls.py`. Small enough
that reading it is faster than reading about it — this file exists to tell you
the few things that are not obvious from the source.

## What it serves

| Path | What |
|---|---|
| `/` | Landing page |
| `/projects/` | Project index and detail pages |
| `/writing/` | Posts |
| `/styleguide/` | Living reference for the design tokens |

## The styleguide is load-bearing

`/styleguide/` renders the Tailwind semantic tokens — `bg-surface`,
`border-border`, `rounded-card`, `text-text-secondary` and the rest — as
actual swatches and components.

It is the reason those tokens stay consistent across three apps. The finance
app deliberately reuses them rather than defining its own, so a change to
`tailwind.config.js` shows up here first.

## Conventions

Everything in [`../../docs/conventions.md`](../../docs/conventions.md) applies.
Two worth repeating:

- **`static/css/tailwind.css` is a committed build artifact.** Heroku runs no
  Node. Re-run `npm run tailwind:build` after template changes and commit the
  result.
- **The site is dark-only.** Theming is out of scope; `tailwind.config.js` is
  not the place to start adding a light mode without a wider decision.

## Tests

`core/tests.py` — a single module, which is proportionate to the app.

```bash
uv run python manage.py test core --settings=datamays.settings_test
```
