from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def money(value, places=2):
    """Format an amount with thousands separators: 41260.64 → 41,260.64.

    Money without separators is genuinely hard to read at a glance, which
    matters on a screen meant to be checked one-handed in a shop.
    """
    if value is None or value == "":
        return "—"

    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return "—"

    return f"{amount:,.{int(places)}f}"


@register.filter
def abs_money(value, places=2):
    """Magnitude only — for figures already labelled as a debt or an outflow."""
    if value is None or value == "":
        return "—"

    try:
        return money(abs(Decimal(str(value))), places)
    except (InvalidOperation, TypeError, ValueError):
        return "—"


@register.filter
def money_sign(value):
    """'-' for a negative amount, '' otherwise — None-safe.

    Pairs with abs_money so a template can prefix the sign without risking
    a None comparison in {% if %}: {{ x|money_sign }}${{ x|abs_money }}.
    """
    if value is None or value == "":
        return ""

    try:
        return "-" if Decimal(str(value)) < 0 else ""
    except (InvalidOperation, TypeError, ValueError):
        return ""


@register.filter
def get_item(mapping, key):
    """Look up a dict by a key held in a variable.

    Needed for the import preview, where the column names are data rather than
    something the template can know in advance.
    """
    if not hasattr(mapping, "get"):
        return ""

    return mapping.get(key, "")
