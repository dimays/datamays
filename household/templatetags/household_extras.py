from decimal import Decimal, InvalidOperation

from django import template

from ..services import wording

register = template.Library()


@register.simple_tag
def due_words(occurrence, today):
    return wording.due_words(occurrence, today)


@register.filter
def money(value, places=2):
    """An amount with separators: 1234.5 → 1,234.50. None reads as a dash.

    The same format as finance's filter of the same name; restated rather
    than loaded from finance's tag library, which is finance's business
    (ADR 0009).
    """
    if value is None or value == "":
        return "—"
    try:
        return f"{Decimal(str(value)):,.{int(places)}f}"
    except (InvalidOperation, TypeError, ValueError):
        return "—"


@register.filter
def absolute(value):
    """The size of an amount without its sign — "$252 over", not "$-252 over"."""
    try:
        return abs(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        return value


@register.filter
def usd(value, places=2):
    """An amount as dollars with its sign in front: "$1,234.50", "-$25.00".

    For the budget figures, where cents matter. Found in review: whole-dollar
    rounding printed "$0 over" for a project $0.40 over budget, and a refund
    read "$-25".
    """
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return "—"
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.{int(places)}f}"
