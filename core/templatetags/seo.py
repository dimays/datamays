from django import template

from core import seo

register = template.Library()


@register.inclusion_tag("core/partials/seo_head.html", takes_context=True)
def seo_head(context, title="", description="", image="", image_alt="", kind="website", suffix=True):
    """The title, description, canonical link and preview-card tags for a page.

    `title` is the page's own name; " — David Mays" is added unless
    `suffix` is False (the home page, whose title is the whole thing).
    """
    request = context.get("request")
    if title and suffix:
        title = f"{title} — {seo.NAME}"
    if image:
        image = seo.absolute(image)
    else:
        image, image_alt = seo.default_image(), seo.DEFAULT_IMAGE_ALT
    return {
        "title": title or seo.DEFAULT_TITLE,
        "description": seo.description(description) or seo.DEFAULT_DESCRIPTION,
        "canonical": seo.canonical_url(request) if request else "",
        "image": image,
        "image_alt": image_alt,
        "kind": kind,
        "site_name": seo.SITE_NAME,
    }


@register.simple_tag
def person_ld():
    return seo.ld_json(seo.person(), seo.website())


@register.simple_tag
def blog_posting_ld(post):
    return seo.ld_json(seo.blog_posting(post))
