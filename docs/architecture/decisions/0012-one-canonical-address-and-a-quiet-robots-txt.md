# 0012 — One canonical address, and a robots.txt that names nothing private

**Status:** accepted (2026-10-25)
**Reverse cost:** low in code; changing the canonical host later costs search ranking while engines catch up

## Context

The public site answers at three hosts: `www.datamays.com`, `datamays.com`
(Cloudflare redirects it to www) and the Heroku app's own `herokuapp.com`
name. Without a canonical address, search engines can list the same page
under more than one of them and split its ranking.

The site had no sitemap, no robots.txt of its own (Cloudflare served a
comments-only one), no meta descriptions and no preview cards, so a shared
link showed a bare title.

## Decision

- **`https://www.datamays.com` is the one address** (`settings.SITE_URL`).
  Every public page's canonical link, the sitemap's URLs, robots.txt and
  preview-card image URLs name it, whichever host served the request.
  The canonical link keeps only `?page=`; other query strings are views of
  the same page.
- **Search metadata lives in one place.** `core/seo.py` builds titles,
  descriptions and the structured data (Person and WebSite on the home and
  about pages, BlogPosting on a post); `{% seo_head %}`
  (`core/templatetags/seo.py`) writes the head tags. Structured data is
  serialized with `json.dumps` and escaped like `json_script`, never
  assembled in a template.
- **robots.txt allows everything and points at the sitemap.** It doesn't
  list `/finance/` or `/household/`. They answer strangers with a 403
  and aren't linked from public pages ([architecture overview](../overview.md#how-a-request-is-served));
  a `Disallow` line would only tell people they exist. Their base
  templates already carry `noindex`.
- **The sitemap holds public pages only:** the main pages, public projects
  and published posts. The styleguide is reachable but left out.
- **A project can name its write-up before the post is published.** The
  "Read the full write-up" link appears only once the post is published,
  checked with one query per page.

## Consequences

- Cloudflare's managed robots.txt, if it's still on, prepends its content
  signals to ours. That's harmless; turning it off leaves ours alone.
- A new public page needs a `{% seo_head title=... description=... %}`
  block, and an entry in `core/sitemaps.py` if it should be found.
- The default preview card (`static/img/og/datamays.png`, 1200×630) is a
  committed image, drawn once from the logo and the site's colors.
