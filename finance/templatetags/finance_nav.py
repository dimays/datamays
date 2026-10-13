from django import template
from django.urls import reverse

register = template.Library()

# Finance's own screens, shown as the section nav strip under the household
# header (finance/partials/section_nav.html). The daily-use, at-a-glance
# screens come first.
PRIMARY_NAV = [
    {"url_name": "home", "label": "Home"},
    {"url_name": "transactions", "label": "Activity"},
    {"url_name": "charts", "label": "Charts"},
    {"url_name": "qfrs", "label": "QFRs", "related": ["qfr_detail"]},
]

# Finance navigation that isn't daily-use, but still belongs in the strip
# rather than buried in the account dropdown (which is reserved for
# user-specific things — preferences, alerts, help, sign out). Import before
# Settings, per an explicit "Settings at the far right" ask.
SECONDARY_NAV = [
    {
        "url_name": "imports",
        "label": "Import",
        "related": ["import_schemas", "import_upload", "import_map", "import_preview"],
    },
    {
        "url_name": "settings",
        "label": "Settings",
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
def finance_section_nav(context):
    """Every finance screen in nav order, for the section nav strip."""
    return _resolve(context, PRIMARY_NAV) + _resolve(context, SECONDARY_NAV)
