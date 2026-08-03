from django import template
from django.urls import reverse

register = template.Library()

# The five screens that earn a spot on a phone's thumb bar. Settings and
# preferences live in the header menu instead — they are not daily-use.
PRIMARY_NAV = [
    {"url_name": "home", "label": "Home", "icon": "home"},
    {"url_name": "transactions", "label": "Activity", "icon": "list"},
    {"url_name": "spend", "label": "Spend", "icon": "chart"},
    {"url_name": "income", "label": "Income", "icon": "income"},
    {"url_name": "savings", "label": "Savings", "icon": "bank"},
]


@register.simple_tag(takes_context=True)
def finance_nav(context):
    """Primary nav items, resolved and flagged with the active screen."""
    request = context.get("request")
    current = getattr(getattr(request, "resolver_match", None), "url_name", None)

    return [
        {
            **item,
            "href": reverse(f"finance:{item['url_name']}"),
            "is_active": item["url_name"] == current,
        }
        for item in PRIMARY_NAV
    ]
