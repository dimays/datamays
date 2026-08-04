from django import template
from django.urls import reverse

register = template.Library()

# The screens that earn a spot on a phone's thumb bar — daily-use, at-a-glance
# screens. Settings, Help, and Import live in the desktop header instead (see
# SECONDARY_NAV): useful, but not something a phone needs one thumb-tap away.
PRIMARY_NAV = [
    {"url_name": "home", "label": "Home", "icon": "home"},
    {"url_name": "transactions", "label": "Activity", "icon": "list"},
    {"url_name": "charts", "label": "Charts", "icon": "chart"},
    {"url_name": "qfrs", "label": "QFRs", "icon": "report", "related": ["qfr_detail"]},
]

# Desktop-header-only items, alongside PRIMARY_NAV. The account dropdown is
# reserved for user-specific things (preferences, alerts, sign out) — these
# are app navigation, so they belong at the top level instead.
SECONDARY_NAV = [
    {
        "url_name": "settings",
        "label": "Settings",
        "related": [
            "institutions", "institution_create", "institution_edit",
            "connection_create", "connection_detail",
            "account_create", "account_edit", "rules",
        ],
    },
    {
        "url_name": "imports",
        "label": "Import data",
        "related": ["import_schemas", "import_upload", "import_map", "import_preview"],
        "is_button": True,
    },
    {"url_name": "help", "label": "Help"},
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
    """Desktop-header-only nav items (Settings, Import, Help)."""
    return _resolve(context, SECONDARY_NAV)
