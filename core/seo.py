"""What search engines and link previews read about the public site.

One canonical address for every page, so the bare domain, www and the
herokuapp.com name don't compete in search results: Cloudflare sends
datamays.com to www, and the canonical link and sitemap name www too.

The structured data says who wrote what (schema.org Person, WebSite and
BlogPosting). It's built here, in Python, and written out with json.dumps,
never assembled in a template, so a quote or a "</script>" in a title can't
break out of the tag.
"""

import json

from django.conf import settings
from django.templatetags.static import static
from django.utils.html import strip_tags
from django.utils.safestring import mark_safe

NAME = "David Mays"
SITE_NAME = "datamays"
DEFAULT_TITLE = "David Mays — data engineer and builder of durable things"
DEFAULT_DESCRIPTION = (
    "David Mays is a data engineer who designs, builds and shares tools and "
    "systems that make data work better. Projects, writing and how he works."
)
DEFAULT_IMAGE = "img/og/datamays.png"
DEFAULT_IMAGE_ALT = "The datamays logo beside the words: David Mays. Data engineer. Lifelong learner. Builder of durable things."

PROFILES = [
    "https://www.linkedin.com/in/maysidavid/",
    "https://github.com/dimays",
]


def absolute(url):
    """A full URL on the canonical host, for a path on this site; a full URL as is."""
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    return settings.SITE_URL + (url if url.startswith("/") else "/" + url)


def default_image():
    return absolute(static(DEFAULT_IMAGE))


def canonical_url(request):
    """This page's address on the canonical host. Only ?page= survives, since
    page 2 of the writing list is a different page; every other query is a
    view of the same one."""
    url = settings.SITE_URL + request.path
    page = request.GET.get("page")
    if page and page.isdigit() and page != "1":
        url += f"?page={page}"
    return url


def description(text, length=160):
    """A meta description from Markdown or HTML: plain words, cut at a word."""
    plain = " ".join(strip_tags(text or "").split())
    if len(plain) <= length:
        return plain
    cut = plain[: length - 1].rsplit(" ", 1)[0].rstrip(",;:")
    return cut if cut.endswith((".", "!", "?")) else cut + "…"


def person():
    return {
        "@type": "Person",
        "@id": settings.SITE_URL + "/#person",
        "name": NAME,
        "url": settings.SITE_URL + "/",
        "jobTitle": "Data engineer",
        "sameAs": PROFILES,
    }


def website():
    return {
        "@type": "WebSite",
        "@id": settings.SITE_URL + "/#website",
        "name": SITE_NAME,
        "url": settings.SITE_URL + "/",
        "author": {"@id": settings.SITE_URL + "/#person"},
    }


def blog_posting(post):
    url = absolute(post.get_absolute_url())
    data = {
        "@type": "BlogPosting",
        "headline": post.title,
        "description": description(post.summary, 300),
        "url": url,
        "mainEntityOfPage": url,
        "author": {"@type": "Person", "name": NAME, "url": settings.SITE_URL + "/"},
        "image": absolute(post.image_url) or default_image(),
        "keywords": [tag.name for tag in post.tags.all()],
    }
    if post.published_at:
        data["datePublished"] = post.published_at.isoformat()
    if post.updated_at:
        data["dateModified"] = max(post.updated_at, post.published_at or post.updated_at).isoformat()
    return data


def ld_json(*things):
    """One <script type="application/ld+json"> holding every thing given."""
    data = {"@context": "https://schema.org", "@graph": list(things)}
    text = json.dumps(data, ensure_ascii=False)
    # The same escapes as Django's json_script: nothing in the data can end
    # the script element or open a comment.
    text = text.replace("<", "\\u003C").replace(">", "\\u003E").replace("&", "\\u0026")
    return mark_safe(f'<script type="application/ld+json">{text}</script>')
