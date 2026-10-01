from django import template
from django.urls import reverse

register = template.Library()

# The top-level sections, in nav order: the phone's thumb bar and the desktop
# header both render exactly this list. A section is active when the current
# page is in its URL namespace — and, where a namespace is shared, when the
# page's URL name is one of the section's own.
#
# Sections join this list in the phase that builds them. A link to a section
# that does not exist yet would be a dead end on a phone.
SECTIONS = [
    {
        "label": "Today",
        "url": "household:today",
        "icon": "today",
        "namespace": "household",
        "url_names": {"today"},
    },
    {
        "label": "Finance",
        "url": "finance:home",
        "icon": "finance",
        "namespace": "finance",
    },
]


def _is_active(section, match):
    if match is None or match.namespace != section["namespace"]:
        return False

    names = section.get("url_names")
    return names is None or match.url_name in names


@register.simple_tag(takes_context=True)
def household_sections(context):
    """The top-level sections, resolved and flagged with the current one."""
    request = context.get("request")
    match = getattr(request, "resolver_match", None)

    return [
        {**section, "href": reverse(section["url"]), "is_active": _is_active(section, match)}
        for section in SECTIONS
    ]
