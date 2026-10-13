"""Dates in the words a person would use — shared by templates and email."""

from datetime import timedelta


def _short(day, today):
    words = f"{day:%a}, {day:%b} {day.day}"
    return words if day.year == today.year else f"{words}, {day.year}"


def due_words(occurrence, today):
    """When an open occurrence is due, as a person would say it.

    "Today", "Tomorrow", or a short date — plus "by <date>" when a deadline
    gives it longer than its due date, and "3 days overdue" once it is late.
    """
    # Overdue before "Whenever": an undated one-off can still be late against
    # its deadline.
    if occurrence.is_overdue(today):
        days = occurrence.days_overdue(today)
        return f"{days} day{'' if days == 1 else 's'} overdue"

    if occurrence.due_on is None:
        return "Whenever"

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
