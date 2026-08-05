from django import template
from django.urls import reverse

register = template.Library()

# The daily-use, at-a-glance screens — first in line on both the phone's
# thumb bar and the desktop header.
PRIMARY_NAV = [
    {"url_name": "home", "label": "Home", "icon": "home"},
    {"url_name": "transactions", "label": "Activity", "icon": "list"},
    {"url_name": "charts", "label": "Charts", "icon": "chart"},
    {"url_name": "qfrs", "label": "QFRs", "icon": "report", "related": ["qfr_detail"]},
]

# App navigation that isn't daily-use, but still belongs at the top level
# rather than buried in the account dropdown (which is reserved for
# user-specific things — preferences, alerts, help, sign out). Shown on both
# the desktop header and the mobile tab bar, so the two never drift apart.
# Import before Settings, per an explicit "Settings at the far right" ask.
SECONDARY_NAV = [
    {
        "url_name": "imports",
        "label": "Import data",
        "icon": "upload",
        "related": ["import_schemas", "import_upload", "import_map", "import_preview"],
    },
    {
        "url_name": "settings",
        "label": "Settings",
        "icon": "settings",
        "related": [
            "institutions", "institution_create", "institution_edit",
            "connection_create", "connection_detail",
            "account_create", "account_edit", "rules",
        ],
    },
]


def _resolve(context, items):
    request = context.get("request")
    current = getattr(getattr(request, "resolver_match", None), "url_name", None)

    return [
        {
            **item,
            "href": reverse(f"finance:{item['url_name']}"),
            "is_active": current == item["url_name"] or current in item.get("related", []),
        }
        for item in items
    ]


@register.simple_tag(takes_context=True)
def finance_nav(context):
    """Primary nav items, resolved and flagged with the active screen."""
    return _resolve(context, PRIMARY_NAV)


@register.simple_tag(takes_context=True)
def finance_secondary_nav(context):
    """Secondary nav items (Import, Settings) — shown on both the desktop
    header and the mobile tab bar, after the primary items."""
    return _resolve(context, SECONDARY_NAV)
