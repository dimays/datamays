"""The one door from the household into finance (ADR 0009).

Everything household code needs from finance comes through here, and only
here — a test fails on any other household module importing `finance`. It
reads; it never writes a finance model.

Keeping it in one place is what lets finance's conventions (Decimal money,
the household sign convention, materialized budget periods) be honored once
rather than by every caller, and it gives a finance refactor exactly one
household file to check.
"""

from decimal import Decimal

from django.db.models import Q

from finance.models import Transaction, UserPreference
from finance.services.analytics import spend_filter
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


# --- transactions ------------------------------------------------------------
#
# Household links transactions to projects and maintenance jobs with its own
# rows (models/budgets.py). Everything it needs to *read* about them comes
# from here, in household terms: "spent" is a positive number, computed from
# finance's signed amount (ADR 0003) in exactly one function below.

# Where a house project's or a repair's spending usually lands, so the
# suggestions start in the right place. Searching by merchant reaches
# everything else.
HOME_CATEGORY_SLUGS = [
    "housing-improvement",
    "housing-maintenance",
    "housing-furnishings",
    "shopping-household",
    "shopping-general",
]

SUGGESTION_LIMIT = 25


def spent(transaction):
    """How much a transaction spent, as a positive Decimal.

    The one place household turns finance's sign convention around: money
    leaving is negative in finance, so a purchase of $42.50 (stored -42.50)
    spent 42.50, and a refund (stored +10.00) spent -10.00, netting back
    against the purchase it corrects.
    """
    return -transaction.amount


def total_spent(transactions):
    return sum((spent(txn) for txn in transactions), Decimal("0"))


def still_spending(transaction_ids):
    """Which of these transactions finance still counts as spending.

    Linked rows are re-checked on every read, not only when linked, so a
    purchase finance later marks as a transfer stops counting in household
    totals too.
    """
    return set(
        Transaction.objects.filter(spend_filter(), pk__in=list(transaction_ids)).values_list("pk", flat=True)
    )


def get_transaction(pk):
    """A spending transaction by id, or None — for validating a posted link.

    Held to the same `spend_filter` as the suggestions, so a posted
    transfer or paycheck id can't be linked either: a project's actual must
    never count what finance's own reports wouldn't.
    """
    try:
        pk = int(pk)
    except (TypeError, ValueError):
        return None
    return Transaction.objects.select_related("account", "category").filter(spend_filter(), pk=pk).first()


def spending_candidates(*, start, end, query="", exclude_ids=(), home_only=True):
    """Transactions that could be linked: spend within [start, end].

    Uses finance's own definition of spend (`spend_filter`) — no transfers,
    refunds netting against expense categories — so a project's "actual"
    can never count something finance's own reports wouldn't. With a
    `query`, matches merchant or description across every category;
    without one, suggests only the home categories above.
    """
    candidates = (
        Transaction.objects.filter(spend_filter(), posted_on__gte=start, posted_on__lte=end)
        .exclude(pk__in=list(exclude_ids))
        .select_related("account", "category")
        .order_by("-posted_on", "-id")
    )
    if query:
        candidates = candidates.filter(Q(merchant__icontains=query) | Q(description_raw__icontains=query))
    elif home_only:
        candidates = candidates.filter(category__slug__in=HOME_CATEGORY_SLUGS)

    results = list(candidates[:SUGGESTION_LIMIT])
    # Carried on each row so templates show "spent" without re-deriving it
    # from the signed amount — that conversion lives in spent() alone.
    for txn in results:
        txn.spent = spent(txn)
    return results
