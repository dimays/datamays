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
| `/sitemap.xml`, `/robots.txt` | For search engines (`core/sitemaps.py`, `core/views.py`) |

## Search and link previews

Every public page names `https://www.datamays.com` as its canonical address,
with a description and a preview card for shared links. See
[ADR 0012](../../docs/architecture/decisions/0012-one-canonical-address-and-a-quiet-robots-txt.md).

- A page sets its head with `{% load seo %}` and
  `{% block seo %}{% seo_head title="About me" description="..." %}{% endblock %}`.
  The title gets " — David Mays" added. With no arguments you get the
  site's defaults.
- A project or post with an **image URL** uses it at the top of the page
  and as its preview card (1200×630 is best). It can be a full URL or a
  `/static/img/...` path. Without one, the site's card is used.
- Structured data comes from `core/seo.py` (`{% person_ld %}`,
  `{% blog_posting_ld post %}`); add new kinds there, not in templates.
- Pages that shouldn't be indexed (errors, the contact form's thank-you)
  fill `{% block robots %}` with a `noindex` meta tag.

## Projects and posts

Both are written in the admin, in Markdown. A project's sections are all
optional except "Why I built this"; each renders under a fixed heading,
in this order: What it is, Why I built this, Expected outcome, How it's
built, Challenges & tradeoffs, Lessons learned. Raw HTML passes through,
which is how a `<figure>` with a sized, lazy-loaded image goes in.

A hidden project (`is_public` off) is a draft: staff can open its page,
everyone else gets a 404, and it's left out of the sitemap.

The Unnecessary Obstacles page and its draft write-up arrived in a data
migration (`core/migrations/0006_...`) so they could be reviewed in a pull
request. They're ordinary rows now; edit them in the admin.

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
