"""Charts: every chart the household uses to understand its money, in one
customisable page.

One view resolves a date range, resolution, and account filter from the query
string, falling back to the person's saved dashboard filters, then hands
plain series to the template. All the arithmetic lives in services.analytics
so it can be tested without rendering anything.

Not every chart on the page follows the shared resolution selector — balance
history (net worth, balances over time) is daily-carried-forward by nature,
and budget attainment follows each budget's own anchored period, so forcing
either onto weekly/monthly/quarterly/annually would misrepresent what they
actually are. The resolution applies to the flow-based charts: spend over
time, spend by category over time, recurring expenses, net income, and net
cash flow.

Which sections show, and in what order, is per-person (UserPreference.
chart_sections) — set from Preferences' drag-to-reorder list, or from the
Hide chart / Hidden charts controls right on this page. Both write to the
exact same field, so there is only ever one source of truth for it.
"""

from datetime import timedelta
from urllib.parse import urlencode

from django.shortcuts import redirect
from django.urls import reverse

from .dates import household_today
from .models import (
    Account,
    Budget,
    Category,
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

# Charts tab sections a person can choose to show, hide, and reorder, from
# Preferences or from the Hide chart / Hidden charts controls on the Charts
# tab itself — both write to the same UserPreference.chart_sections, so the
# two are always in sync. Each slug maps to a template partial at
# finance/dashboards/sections/<slug>.html.
CHART_SECTION_CHOICES = [
    ("spend_over_time", "Spend over time"),
    ("spend_by_category_trend", "Spend by category, over time"),
    ("spend_by_category", "Spend by category"),
    ("large_transactions", "Largest transactions"),
    ("recurring_expenses", "Recurring expenses, over time"),
    ("budget_attainment", "Budget attainment"),
    ("net_income", "Net income"),
    ("net_cash_flow", "Net cash flow"),
    ("net_worth", "Net worth"),
    ("balances_over_time", "Balances over time"),
    ("accounts_list", "Savings & debt accounts"),
]


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

    def resolve_balances_accounts(self):
        """A filter scoped to just the balances-over-time chart.

        Kept separate from resolve_accounts(): the page's shared account
        filter narrows the flow-based charts (spend, income, cash flow) to
        the accounts money actually moves through, but a balance line chart
        is just as meaningful for a 401(k) or a mortgage — accounts that
        would never appear in a spend/income filter at all.
        """
        raw = self.request.GET.getlist("balances_account")
        return [int(value) for value in raw if str(value).isdigit()]

    def resolve_large_transactions_accounts(self):
        # Its own filter too, for the same reason as balances: someone
        # exploring "what are the biggest one-off outflows" wants to narrow
        # by account independently of whatever the page's shared filter
        # happens to be set to.
        raw = self.request.GET.getlist("lt_account")
        return [int(value) for value in raw if str(value).isdigit()]

    def resolve_large_transactions_categories(self):
        raw = self.request.GET.getlist("lt_category")
        return [int(value) for value in raw if str(value).isdigit()]

    def resolve_large_transactions_page(self):
        try:
            page = int(self.request.GET.get("lt_page", 1))
        except (TypeError, ValueError):
            return 1
        return max(1, page)

    def known_sections(self):
        return {slug for slug, _ in CHART_SECTION_CHOICES}

    def effective_chart_sections(self):
        """The person's chosen sections, filtered to ones that still exist —
        a section retired from CHART_SECTION_CHOICES should not linger in a
        saved preference forever."""
        known = self.known_sections()
        return [slug for slug in self.get_preference().chart_section_order if slug in known]

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")

        if action in {"hide_section", "show_section"}:
            return self._toggle_section(request, action)

        return self.get(request, *args, **kwargs)

    def _toggle_section(self, request, action):
        """Hide chart / Show chart — the same UserPreference.chart_sections
        Preferences' drag-to-reorder list edits, just a faster path to it
        from the chart itself. Showing a hidden chart puts it at the end of
        the visible list, per the same "arrange it yourself" philosophy as
        everything else here."""
        preference = self.get_preference()
        current = self.effective_chart_sections()
        section = request.POST.get("section")

        if action == "hide_section" and section in current:
            current.remove(section)
        elif action == "show_section" and section in self.known_sections() and section not in current:
            current.append(section)

        preference.chart_sections = current
        preference.save(update_fields=["chart_sections", "updated_at"])

        # Preserve whatever range/grain/account filters were active — hiding
        # or showing one chart shouldn't reset the rest of the page.
        return redirect(request.get_full_path())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        range_key, start, end = self.resolve_range()
        grain = self.resolve_grain(range_key)
        account_ids = self.resolve_accounts()

        chart_sections = self.effective_chart_sections()
        hidden_sections = [
            (slug, label)
            for slug, label in CHART_SECTION_CHOICES
            if slug not in chart_sections
        ]

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
                "chart_sections": chart_sections,
                "hidden_sections": hidden_sections,
                "current_path": self.request.get_full_path(),
            }
        )

        context.update(self._spend_context(start, end, grain, account_ids))
        context.update(self._income_context(start, end, grain, account_ids))
        context.update(self._cash_flow_context(start, end, grain, account_ids))
        context.update(self._large_transactions_context(start, end))
        context.update(self._recurring_expenses_context(start, end, grain, account_ids))
        context.update(self._net_worth_context(start, end))
        context.update(self._balances_over_time_context(start, end))
        context.update(self._accounts_list_context())

        # A section is only worth a "Hide chart" button once it actually has
        # something to hide. Several slugs share one underlying data source
        # (all four spend-side sections empty together, since they all read
        # from the same window of transactions), so this is a lookup rather
        # than a fifth copy of each flag.
        context["section_has_data"] = {
            "spend_over_time": context["spend_has_data"],
            "spend_by_category_trend": context["spend_has_data"],
            "spend_by_category": context["spend_has_data"],
            "large_transactions": context["large_transactions_available"],
            "recurring_expenses": context["recurring_expenses_has_data"],
            "budget_attainment": context["spend_has_data"],
            "net_income": context["income_has_data"],
            "net_cash_flow": context["cash_flow_has_data"],
            "net_worth": context["net_worth_has_data"],
            "balances_over_time": context["balances_over_time_available"],
            "accounts_list": context["accounts_list_has_data"],
        }

        context["has_any_data"] = any(
            [
                context["spend_has_data"],
                context["income_has_data"],
                context["cash_flow_has_data"],
                context["large_transactions_available"],
                context["recurring_expenses_has_data"],
                context["net_worth_has_data"],
                context["balances_over_time_available"],
                context["accounts_list_has_data"],
            ]
        )

        return context

    def _spend_context(self, start, end, grain, account_ids):
        over_time = analytics.spend_over_time(
            start, end, grain=grain, account_ids=account_ids
        )
        by_category = analytics.spend_by_category(start, end, account_ids=account_ids)
        by_category_breakdown = analytics.spend_by_category_breakdown(
            start, end, account_ids=account_ids
        )
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
            "spend_by_category_breakdown_json": by_category_breakdown,
            "spend_by_category_over_time_json": by_category_over_time,
            "spend_total": by_category["total"],
            "budgets": budgets,
            "budget_series_json": budget_series,
            "spend_has_data": bool(over_time["values"]),
        }

    def _income_context(self, start, end, grain, account_ids):
        # The primary figure: every income-categorized deposit, whether or
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

    def _large_transactions_context(self, start, end):
        per_page = 10
        selected_accounts = self.resolve_large_transactions_accounts()
        selected_categories = self.resolve_large_transactions_categories()
        page = self.resolve_large_transactions_page()

        result = analytics.largest_transactions(
            start,
            end,
            account_ids=selected_accounts or None,
            category_ids=selected_categories or None,
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        total_pages = max(1, -(-result["total"] // per_page))

        previous_url = None
        if page > 1:
            query = self.request.GET.copy()
            query["lt_page"] = page - 1
            previous_url = f"{self.request.path}?{query.urlencode()}"

        next_url = None
        if page < total_pages:
            query = self.request.GET.copy()
            query["lt_page"] = page + 1
            next_url = f"{self.request.path}?{query.urlencode()}"

        return {
            "large_transactions": result["transactions"],
            "large_transactions_has_data": result["has_data"],
            "large_transactions_total": result["total"],
            "large_transactions_page": page,
            "large_transactions_total_pages": total_pages,
            "large_transactions_previous_url": previous_url,
            "large_transactions_next_url": next_url,
            "large_transactions_accounts": Account.objects.filter(is_active=True),
            "large_transactions_categories": Category.objects.filter(
                is_active=True, children__isnull=True
            ).select_related("parent").alphabetical(),
            "large_transactions_selected_accounts": [str(a) for a in selected_accounts],
            "large_transactions_selected_categories": [str(c) for c in selected_categories],
            # Whether the section is available at all, regardless of the
            # current per-chart filter/page — a filter that happens to match
            # nothing must not also hide the filter controls themselves, or
            # there'd be no way back to a wider result.
            "large_transactions_available": analytics.largest_transactions(
                start, end, limit=1
            )["has_data"],
        }

    def _recurring_expenses_context(self, start, end, grain, account_ids):
        recurring = analytics.recurring_expenses_over_time(
            start, end, grain=grain, account_ids=account_ids
        )

        return {
            "recurring_expenses_json": recurring,
            "recurring_expenses_has_data": recurring["has_data"],
        }

    def _net_worth_context(self, start, end):
        net_worth = analytics.net_worth_history(start=start, end=end)

        return {
            "net_worth_json": net_worth,
            # values is always one entry per day in the window — a null for
            # every day it is, until at least one snapshot exists.
            "net_worth_has_data": any(v is not None for v in net_worth["values"]),
        }

    def _balances_over_time_context(self, start, end):
        # Its own account filter, not the page's shared one: every account
        # has a balance worth charting, including ones (401(k), mortgage)
        # that would never appear in a spend/income filter.
        selected = self.resolve_balances_accounts()
        history = analytics.balance_history(
            account_ids=selected or None, start=start, end=end
        )

        return {
            "balances_over_time_json": self._to_chart(history),
            "balances_over_time_has_data": bool(history["series"]),
            # Whether the chart is available at all, regardless of the
            # current per-chart account filter — a filter that happens to
            # pick accounts with no history yet must not also hide the
            # filter control itself, or there would be no way back.
            "balances_over_time_available": bool(
                analytics.balance_history(start=start, end=end)["series"]
            ),
            "selected_balances_accounts": selected,
        }

    def _accounts_list_context(self):
        accounts = list(
            Account.objects.filter(
                is_active=True, account_type__in=self.SAVINGS_TYPES + self.DEBT_TYPES
            ).select_related("institution")
        )

        return {
            "savings_debt_accounts": accounts,
            # These are the accounts no aggregator can reach, so their
            # balances only move when a statement is imported or someone
            # updates them by hand.
            "manual_savings_debt_accounts": [a for a in accounts if a.is_manual],
            # A savings/debt-type account with no balance yet (freshly added,
            # never synced) isn't worth its own list row.
            "accounts_list_has_data": any(a.current_balance is not None for a in accounts),
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
