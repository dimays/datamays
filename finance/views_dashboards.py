"""Spend, Income, and Savings & Debt.

Each view resolves a date range and account filter from the query string,
falling back to the person's saved dashboard filters, then hands plain series
to the template. All the arithmetic lives in services.analytics so it can be
tested without rendering anything.
"""

from datetime import timedelta

from django.utils import timezone

from .access import FinanceAccessMixin
from .models import (
    Account,
    AccountType,
    Budget,
    UserPreference,
)
from .services import analytics
from .views import FinanceView

RANGE_CHOICES = [
    ("3m", "3 months", 90),
    ("6m", "6 months", 182),
    ("12m", "12 months", 365),
    ("24m", "2 years", 730),
]

RANGE_DAYS = {key: days for key, _, days in RANGE_CHOICES}

GRAIN_CHOICES = [("daily", "Daily"), ("weekly", "Weekly"), ("monthly", "Monthly")]


class DashboardView(FinanceView):
    """Shared filter handling: range, grain, and account selection."""

    dashboard_slug = ""

    def get_preference(self):
        return UserPreference.for_user(self.request.user)

    def saved_filters(self):
        return (self.get_preference().dashboard_filters or {}).get(
            self.dashboard_slug, {}
        )

    def resolve_range(self):
        saved = self.saved_filters()
        key = self.request.GET.get("range") or saved.get("range") or "12m"

        end = timezone.localdate()
        start = end - timedelta(days=RANGE_DAYS.get(key, 365))

        return key, start, end

    def resolve_grain(self):
        saved = self.saved_filters()
        grain = self.request.GET.get("grain") or saved.get("grain") or "monthly"

        return grain if grain in dict(GRAIN_CHOICES) else "monthly"

    def resolve_accounts(self):
        raw = self.request.GET.getlist("account")

        if not raw:
            raw = self.saved_filters().get("accounts") or []

        return [int(value) for value in raw if str(value).isdigit()]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        range_key, start, end = self.resolve_range()

        context.update(
            {
                "dashboard_slug": self.dashboard_slug,
                "range_choices": RANGE_CHOICES,
                "grain_choices": GRAIN_CHOICES,
                "selected_range": range_key,
                "selected_grain": self.resolve_grain(),
                "selected_accounts": self.resolve_accounts(),
                "all_accounts": Account.objects.filter(is_active=True),
                "start": start,
                "end": end,
            }
        )

        return context


class SpendView(DashboardView):
    template_name = "finance/dashboards/spend.html"
    page_title = "Spend"
    dashboard_slug = "spend"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        start, end = context["start"], context["end"]
        account_ids = context["selected_accounts"]

        over_time = analytics.spend_over_time(
            start, end, grain=context["selected_grain"], account_ids=account_ids
        )
        by_category = analytics.spend_by_category(start, end, account_ids=account_ids)

        budgets = Budget.objects.filter(is_active=True).prefetch_related("budget_periods")

        context.update(
            {
                "over_time_json": over_time,
                "by_category_json": by_category,
                "total": by_category["total"],
                "budgets": budgets,
                "budget_series_json": [
                    {
                        "name": budget.name,
                        **analytics.budget_attainment_over_time(budget),
                    }
                    for budget in budgets
                ],
                "has_data": bool(over_time["values"]),
            }
        )

        return context


class IncomeView(DashboardView):
    template_name = "finance/dashboards/income.html"
    page_title = "Income"
    dashboard_slug = "income"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        start, end = context["start"], context["end"]

        income = analytics.income_over_time(start, end)
        unmatched = analytics.deposits_without_paychecks(start, end)

        context.update(
            {
                "income_series_json": {
                    "labels": income["labels"],
                    "series": [
                        {"label": "Gross", "values": income["gross"]},
                        {"label": "Net", "values": income["net"]},
                    ],
                },
                # Retirement and HSA are their own line rather than being
                # lumped in with tax: that money is still the household's, and
                # showing it as lost would understate what they actually earn.
                "income_breakdown_json": {
                    "labels": income["labels"],
                    "series": [
                        {"label": "Take-home", "values": income["net"]},
                        {"label": "Tax", "values": income["tax"]},
                        {"label": "Retirement & HSA", "values": income["retained"]},
                        {"label": "Other deductions", "values": income["other"]},
                    ],
                },
                "has_data": income["has_data"],
                # Surfaced rather than silently under-reporting: gross and tax
                # only exist where a payslip has been imported.
                "unmatched_deposits": unmatched[:10],
                "unmatched_count": unmatched.count(),
            }
        )

        return context


class SavingsView(DashboardView):
    template_name = "finance/dashboards/savings.html"
    page_title = "Savings & Debt"
    dashboard_slug = "savings"

    SAVINGS_TYPES = [
        AccountType.SAVINGS,
        AccountType.MONEY_MARKET,
        AccountType.INVESTMENT,
        AccountType.RETIREMENT,
        AccountType.INSURANCE,
    ]

    DEBT_TYPES = [
        AccountType.STUDENT_LOAN,
        AccountType.MORTGAGE,
        AccountType.AUTO_LOAN,
        AccountType.CREDIT_CARD,
    ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        start, end = context["start"], context["end"]

        savings = analytics.balance_history(
            start=start, end=end, account_types=self.SAVINGS_TYPES
        )
        debts = analytics.balance_history(
            start=start, end=end, account_types=self.DEBT_TYPES
        )
        net_worth = analytics.net_worth_history(start=start, end=end)

        accounts = list(
            Account.objects.filter(
                is_active=True, account_type__in=self.SAVINGS_TYPES + self.DEBT_TYPES
            ).select_related("institution")
        )

        context.update(
            {
                "savings_json": self._to_chart(savings),
                "debts_json": self._to_chart(debts, magnitude=True),
                "net_worth_json": net_worth,
                "accounts": accounts,
                # These are the accounts no aggregator can reach, so their
                # charts only move when a statement is imported.
                "manual_accounts": [a for a in accounts if a.is_manual],
                "has_data": bool(savings["series"] or debts["series"]),
            }
        )

        return context

    @staticmethod
    def _to_chart(history, magnitude=False):
        return {
            "labels": history["labels"],
            "series": [
                {
                    "label": series["label"],
                    "values": [
                        None if value is None else (abs(value) if magnitude else value)
                        for value in series["values"]
                    ],
                }
                for series in history["series"]
            ],
        }
