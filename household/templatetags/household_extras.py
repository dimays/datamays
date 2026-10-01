from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


def _short(day, today):
    words = f"{day:%a}, {day:%b} {day.day}"
    return words if day.year == today.year else f"{words}, {day.year}"


@register.simple_tag
def due_words(occurrence, today):
    """When an open occurrence is due, as a person would say it.

    "Today", "Tomorrow", or a short date — plus "by <date>" when a deadline
    gives it longer than its due date, and "3 days overdue" once it is late.
    """
    if occurrence.due_on is None:
        return "Whenever"

    if occurrence.is_overdue(today):
        days = occurrence.days_overdue(today)
        return f"{days} day{'' if days == 1 else 's'} overdue"

    if occurrence.due_on == today:
        words = "Today"
    elif occurrence.due_on == today + timedelta(days=1):
        words = "Tomorrow"
    elif occurrence.due_on < today:
        words = f"Due since {_short(occurrence.due_on, today)}"
    else:
        words = _short(occurrence.due_on, today)

    if occurrence.deadline and occurrence.deadline != occurrence.due_on:
        words += f" · by {_short(occurrence.deadline, today)}"
    return words


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
