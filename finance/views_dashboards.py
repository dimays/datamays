"""Charts: spend, income, cash flow, and savings & debt in one place.

One view resolves a date range, resolution, and account filter from the query
string, falling back to the person's saved dashboard filters, then hands
plain series to the template. All the arithmetic lives in services.analytics
so it can be tested without rendering anything.

Not every chart on the page follows the shared resolution selector — balance
history (net worth, savings, debt) is daily-carried-forward by nature, and
budget attainment follows each budget's own anchored period, so forcing
either onto weekly/monthly/quarterly/annually would misrepresent what they
actually are. The resolution applies to the four flow-based charts: spend
over time, net income, net cash flow, and spend by category over time.
"""

from datetime import timedelta
from urllib.parse import urlencode

from django.urls import reverse

from .dates import household_today
from .models import (
    Account,
    Budget,
    DEBT_TYPES,
    SAVINGS_TYPES,
    UserPreference,
)
from .services import analytics
from .views import FinanceView


def _transactions_url(**params):
    """A link to the activity list, carrying forward whatever filters apply.

    Multi-value params (repeated `account=`) need urlencode(doseq=True) —
    Django's own querystring builder doesn't take a plain dict of lists.
    """
    query = {key: value for key, value in params.items() if value not in (None, "", [])}
    return f"{reverse('finance:transactions')}?{urlencode(query, doseq=True)}"


RANGE_CHOICES = [
    ("3m", "3 months", 90),
    ("6m", "6 months", 182),
    ("12m", "12 months", 365),
    ("24m", "2 years", 730),
]

RANGE_DAYS = {key: days for key, _, days in RANGE_CHOICES}

GRAIN_CHOICES = [
    ("weekly", "Weekly"),
    ("monthly", "Monthly"),
    ("quarterly", "Quarterly"),
    ("annually", "Annually"),
]

# A resolution only makes sense once the selected range can actually show a
# handful of it — "Annually" over a 3-month window would draw one bar and
# call it a trend. Minimums are deliberately generous (not "exactly one
# period") so there's always at least a couple of points on the chart.
GRAIN_MIN_RANGE_DAYS = {
    "weekly": 0,
    "monthly": 0,
    "quarterly": 182,
    "annually": 365,
}


class ChartsView(FinanceView):
    """Shared filter handling: range, resolution, and account selection."""

    template_name = "finance/dashboards/charts.html"
    page_title = "Charts"
    dashboard_slug = "charts"

    # Shared with the QFR's own metrics, so the two can never quietly
    # classify an account type differently from each other.
    SAVINGS_TYPES = list(SAVINGS_TYPES)
    DEBT_TYPES = list(DEBT_TYPES)

    def get_preference(self):
        return UserPreference.for_user(self.request.user)

    def saved_filters(self):
        return (self.get_preference().dashboard_filters or {}).get(
            self.dashboard_slug, {}
        )

    def resolve_range(self):
        saved = self.saved_filters()
        key = self.request.GET.get("range") or saved.get("range") or "12m"

        if key not in RANGE_DAYS:
            key = "12m"

        end = household_today()
        start = end - timedelta(days=RANGE_DAYS[key])

        return key, start, end

    def available_grains(self, range_key):
        range_days = RANGE_DAYS.get(range_key, 365)
        return [
            (key, label)
            for key, label in GRAIN_CHOICES
            if range_days >= GRAIN_MIN_RANGE_DAYS[key]
        ]

    def resolve_grain(self, range_key):
        saved = self.saved_filters()
        requested = self.request.GET.get("grain") or saved.get("grain") or "monthly"

        valid = dict(self.available_grains(range_key))

        if requested in valid:
            return requested

        # Fell out of range (e.g. switched to a 3-month window with
        # "Annually" selected) — monthly always fits every range, so it's
        # the one sensible fallback rather than silently picking whatever
        # happens to be first.
        return "monthly"

    def resolve_accounts(self):
        raw = self.request.GET.getlist("account")

        if not raw:
            raw = self.saved_filters().get("accounts") or []

        return [int(value) for value in raw if str(value).isdigit()]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        range_key, start, end = self.resolve_range()
        grain = self.resolve_grain(range_key)
        account_ids = self.resolve_accounts()

        context.update(
            {
                "range_choices": RANGE_CHOICES,
                "grain_choices": self.available_grains(range_key),
                "selected_range": range_key,
                "selected_grain": grain,
                "selected_accounts": account_ids,
                "all_accounts": Account.objects.filter(is_active=True),
                "start": start,
                "end": end,
            }
        )

        context.update(self._spend_context(start, end, grain, account_ids))
        context.update(self._income_context(start, end, grain, account_ids))
        context.update(self._cash_flow_context(start, end, grain, account_ids))
        context.update(self._savings_context(start, end))

        context["has_any_data"] = any(
            [
                context["spend_has_data"],
                context["income_has_data"],
                context["cash_flow_has_data"],
                context["savings_has_data"],
            ]
        )

        return context

    def _spend_context(self, start, end, grain, account_ids):
        over_time = analytics.spend_over_time(
            start, end, grain=grain, account_ids=account_ids
        )
        by_category = analytics.spend_by_category(start, end, account_ids=account_ids)
        by_category_over_time = analytics.spend_by_category_over_time(
            start, end, grain=grain, account_ids=account_ids
        )

        # One link per bar, built server-side from the exact bounds that
        # produced its number — so a click shows precisely what's behind it,
        # not a re-derived approximation. Carries forward the account filter
        # already active on this page.
        over_time["links"] = [
            _transactions_url(
                spend="1", start=bucket_start, end=bucket_end, account=account_ids
            )
            for bucket_start, bucket_end in zip(
                over_time["bucket_starts"], over_time["bucket_ends"]
            )
        ]

        budgets = Budget.objects.filter(is_active=True).prefetch_related("budget_periods")
        budget_series = []
        for budget in budgets:
            series = analytics.budget_attainment_over_time(budget)
            series["links"] = [
                _transactions_url(budget=budget.pk, start=period_start, end=period_end)
                for period_start, period_end in zip(
                    series["period_starts"], series["period_ends"]
                )
            ]
            budget_series.append({"name": budget.name, **series})

        return {
            "spend_over_time_json": over_time,
            "spend_by_category_json": by_category,
            "spend_by_category_over_time_json": by_category_over_time,
            "spend_total": by_category["total"],
            "budgets": budgets,
            "budget_series_json": budget_series,
            "spend_has_data": bool(over_time["values"]),
        }

    def _income_context(self, start, end, grain, account_ids):
        # The primary figure: every income-categorised deposit, whether or
        # not a payslip was ever imported for it. Works for a household
        # member whose pay never gets a detailed payslip.
        net_income = analytics.net_income_over_time(
            start, end, grain=grain, account_ids=account_ids
        )

        # Optional supplementary detail, layered on top for whichever pay
        # periods do have an imported payslip. Deliberately not filtered by
        # account or resolution -- payslips are discrete pay-period events,
        # not something that rolls up cleanly to an arbitrary grain.
        payslip_detail = analytics.income_over_time(start, end)
        unmatched = analytics.deposits_without_paychecks(start, end)

        return {
            "net_income_json": {
                "labels": net_income["labels"],
                "values": net_income["values"],
            },
            "income_has_data": net_income["has_data"],
            "has_payslip_detail": payslip_detail["has_data"],
            # Retirement and HSA are their own line rather than being lumped
            # in with tax: that money is still the household's, and showing
            # it as lost would understate what they actually earn.
            "payslip_breakdown_json": {
                "labels": payslip_detail["labels"],
                "series": [
                    {"label": "Take-home", "values": payslip_detail["net"]},
                    {"label": "Tax", "values": payslip_detail["tax"]},
                    {"label": "Retirement & HSA", "values": payslip_detail["retained"]},
                    {"label": "Other deductions", "values": payslip_detail["other"]},
                ],
            },
            "payslip_gross_json": {
                "labels": payslip_detail["labels"],
                "series": [
                    {"label": "Gross", "values": payslip_detail["gross"]},
                    {"label": "Net", "values": payslip_detail["net"]},
                ],
            },
            # A pointer toward optional payslip import, not a warning that
            # anything is broken — net income already counts these.
            "unmatched_deposits": unmatched[:10],
            "unmatched_count": unmatched.count(),
        }

    def _cash_flow_context(self, start, end, grain, account_ids):
        cash_flow = analytics.net_cash_flow_over_time(
            start, end, grain=grain, account_ids=account_ids
        )

        return {
            "cash_flow_json": cash_flow,
            "cash_flow_has_data": cash_flow["has_data"],
        }

    def _savings_context(self, start, end):
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

        return {
            "savings_json": self._to_chart(savings),
            "debts_json": self._to_chart(debts, magnitude=True),
            "net_worth_json": net_worth,
            "savings_debt_accounts": accounts,
            # These are the accounts no aggregator can reach, so their
            # charts only move when a statement is imported.
            "manual_savings_debt_accounts": [a for a in accounts if a.is_manual],
            "savings_has_data": bool(savings["series"] or debts["series"]),
        }

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
