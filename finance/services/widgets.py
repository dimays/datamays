"""Assembling the homepage.

Each widget is a small, independent builder returning plain data. Keeping them
separate means a slow or empty one degrades on its own rather than taking the
page with it, and the homepage stays a composition rather than one enormous
query.

Everything here reads materialised values — denormalised account balances and
rolled-up budget periods — so the page a phone loads is a handful of indexed
lookups rather than aggregates over the whole ledger.
"""

from decimal import Decimal

from django.utils import timezone

from ..dates import household_today
from ..models import Account, BudgetPeriod, Transaction, UserPreference

WIDGET_CHOICES = [
    ("balances", "Account balances"),
    ("budgets", "Budget attainment"),
    ("recent_transactions", "Recent activity"),
    ("net_worth", "Net worth"),
    ("review_queue", "Needs review"),
]

WIDGET_LABELS = dict(WIDGET_CHOICES)


def _filtered_accounts(preference):
    accounts = Account.objects.filter(is_active=True).select_related("institution")

    if preference.homepage_account_ids:
        accounts = accounts.filter(pk__in=preference.homepage_account_ids)

    return accounts


def balances_widget(preference):
    accounts = list(_filtered_accounts(preference))

    return {
        "accounts": accounts,
        "total": sum(
            (a.current_balance or Decimal("0") for a in accounts if a.include_in_net_worth),
            Decimal("0"),
        ),
        "stale": [a for a in accounts if _is_stale(a)],
    }


def _is_stale(account, days=3):
    """Flag balances old enough to be misleading.

    A quietly failing sync is the worst way for this app to be wrong: the
    numbers look fine, they are just out of date. Manual accounts are exempt —
    they are expected to lag.
    """
    if account.is_manual:
        return False

    if account.balance_as_of is None:
        return True

    return (timezone.now() - account.balance_as_of).days >= days


def net_worth_widget(preference):
    accounts = Account.objects.filter(is_active=True, include_in_net_worth=True)

    assets = Decimal("0")
    liabilities = Decimal("0")

    for account in accounts:
        balance = account.current_balance or Decimal("0")

        if balance >= 0:
            assets += balance
        else:
            liabilities += balance

    return {
        "assets": assets,
        # Returned as a magnitude: the card is labelled "Debts", so a minus
        # sign there reads as a double negative.
        "liabilities": -liabilities,
        "total": assets + liabilities,
    }


def budgets_widget(preference):
    today = household_today()

    periods = (
        BudgetPeriod.objects.filter(
            budget__is_active=True, period_start__lte=today, period_end__gte=today
        )
        .select_related("budget")
        .order_by("budget__name")
    )

    if preference.homepage_budget_ids:
        periods = periods.filter(budget_id__in=preference.homepage_budget_ids)

    rows = [
        {"period": period, "budget": period.budget, "pace": period.pace_difference(today)}
        for period in periods
    ]

    # Worst pace first: the budget most at risk is the one worth seeing before
    # standing at a checkout.
    rows.sort(key=lambda row: row["pace"], reverse=True)

    return {"rows": rows, "over": [row for row in rows if row["period"].is_over]}


def recent_transactions_widget(preference):
    transactions = Transaction.objects.select_related("account", "category").filter(
        is_transfer=False
    )

    if preference.homepage_account_ids:
        transactions = transactions.filter(account_id__in=preference.homepage_account_ids)

    return {"transactions": list(transactions[: preference.recent_transaction_count])}


def review_queue_widget(preference):
    queryset = Transaction.objects.filter(needs_review=True)

    return {
        "count": queryset.count(),
        "transactions": list(
            queryset.select_related("account", "category")[:5]
        ),
    }


BUILDERS = {
    "balances": balances_widget,
    "net_worth": net_worth_widget,
    "budgets": budgets_widget,
    "recent_transactions": recent_transactions_widget,
    "review_queue": review_queue_widget,
}


def build_homepage(user):
    """Only the widgets this person has chosen, in the order they chose."""
    preference = UserPreference.for_user(user)

    widgets = []

    for slug in preference.widgets:
        builder = BUILDERS.get(slug)

        if builder is None:
            # A preference naming a widget that no longer exists should not
            # break the homepage.
            continue

        widgets.append(
            {
                "slug": slug,
                "label": WIDGET_LABELS.get(slug, slug),
                "data": builder(preference),
            }
        )

    return {"widgets": widgets, "preference": preference}
