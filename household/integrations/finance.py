"""The one door from the household into finance (ADR 0009).

Everything household code needs from finance comes through here, and only
here — a test fails on any other household module importing `finance`. It
reads; it never writes a finance model.

Keeping it in one place is what lets finance's conventions (Decimal money,
the household sign convention, materialized budget periods) be honored once
rather than by every caller, and it gives a finance refactor exactly one
household file to check.
"""

from finance.models import UserPreference
from finance.services.widgets import WIDGET_LABELS, budgets_widget


def budget_glance(user):
    """Finance's own budget widget, for the Today screen.

    The same builder and template the finance homepage uses — not a second
    rendering of the same numbers that could drift from the first — and it
    honors the budget selection each person made in finance preferences.
    """
    return {
        "template": "finance/widgets/budgets.html",
        "label": WIDGET_LABELS["budgets"],
        "data": budgets_widget(UserPreference.for_user(user)),
    }
