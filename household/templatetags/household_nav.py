from django import template
from django.urls import reverse

from ..services.checklist import overdue_count

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
        "label": "Chores",
        "url": "household:chores",
        "icon": "chores",
        "namespace": "household",
        "url_names": {
            "chores", "chore_list", "chore_create", "chore_detail", "chore_edit", "chore_delete",
        },
        # Overdue chores show as a count on this section's nav item, so they
        # are visible from every page — including every finance page.
        "badge": "overdue_chores",
    },
    {
        "label": "Upkeep",
        "url": "household:upkeep",
        "icon": "upkeep",
        "namespace": "household",
        "url_names": {
            "upkeep", "upkeep_create", "upkeep_detail", "upkeep_edit", "upkeep_delete",
            "upkeep_library",
        },
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
    """The top-level sections, resolved and flagged with the current one.

    Cached on the request: the header and the phone's tab bar both render
    this, and the overdue badge costs a query each time it is worked out.
    """
    request = context.get("request")
    if not hasattr(request, "_household_sections"):
        request._household_sections = _sections(request)
    return request._household_sections


def _sections(request):
    match = getattr(request, "resolver_match", None)

    badges = {"overdue_chores": lambda: overdue_count(request.user)}

    return [
        {
            **section,
            "href": reverse(section["url"]),
            "is_active": _is_active(section, match),
            "badge_count": badges[section["badge"]]() if "badge" in section else 0,
        }
        for section in SECTIONS
    ]


CHORES_NAV = [
    {"url_name": "chores", "label": "Checklist", "related": set()},
    {
        "url_name": "chore_list",
        "label": "All chores",
        "related": {"chore_create", "chore_detail", "chore_edit", "chore_delete"},
    },
]


def _section_items(context, items):
    request = context.get("request")
    current = getattr(getattr(request, "resolver_match", None), "url_name", None)

    return [
        {
            "label": item["label"],
            "href": reverse(f"household:{item['url_name']}"),
            "is_active": current == item["url_name"] or current in item["related"],
        }
        for item in items
    ]


@register.simple_tag(takes_context=True)
def chores_section_nav(context):
    return _section_items(context, CHORES_NAV)


UPKEEP_NAV = [
    {"url_name": "upkeep", "label": "Items", "related": {"upkeep_create", "upkeep_detail", "upkeep_edit", "upkeep_delete"}},
    {"url_name": "upkeep_library", "label": "Starter list", "related": set()},
]


@register.simple_tag(takes_context=True)
def upkeep_section_nav(context):
    return _section_items(context, UPKEEP_NAV)
