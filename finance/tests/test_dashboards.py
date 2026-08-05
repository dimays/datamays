"""Dashboard aggregations and rendering."""

from datetime import date, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from finance.dates import household_today
from finance.models import (
    AccountBalanceSnapshot,
    AccountConnection,
    AccountType,
    Budget,
    BudgetPeriod,
    Category,
    DeductionKind,
    Paycheck,
    Transaction,
    PaycheckDeduction,
)
from finance.services import analytics
from finance.views_dashboards import RANGE_CHOICES

from .factories import make_account, make_institution, make_transaction
from .test_access import make_user


class AnalyticsTestCase(TestCase):
    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)

        self.user = make_user("david", with_device=True)
        self.institution = make_institution()
        self.connection = AccountConnection.objects.create(
            institution=self.institution, label="Byline", access_secret="x"
        )

        self.checking = make_account(
            self.institution, name="Checking", connection=self.connection
        )
        self.card = make_account(
            self.institution,
            name="Card",
            account_type=AccountType.CREDIT_CARD,
            connection=self.connection,
        )

        self.groceries = Category.objects.get(slug="food-groceries")
        self.restaurants = Category.objects.get(slug="food-restaurants")
        self.fuel = Category.objects.get(slug="transport-fuel")
        self.salary = Category.objects.get(slug="income-salary")

    def sign_in(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["otp_device_id"] = TOTPDevice.objects.get(user=self.user).persistent_id
        session.save()

    def spend(self, amount, category, day, account=None, month=4):
        return make_transaction(
            account or self.checking,
            posted_on=date(2026, month, day),
            amount=Decimal(amount),
            description_raw=f"TXN {month}-{day} {amount} {category.slug}",
            category=category,
        )


class SpendAnalyticsTests(AnalyticsTestCase):
    def test_spend_is_bucketed_by_month_as_positive_numbers(self):
        self.spend("-100.00", self.groceries, 5, month=3)
        self.spend("-50.00", self.groceries, 6, month=3)
        self.spend("-80.00", self.groceries, 5, month=4)

        result = analytics.spend_over_time(
            date(2026, 3, 1), date(2026, 4, 30), grain="monthly"
        )

        self.assertEqual(result["values"], [150.0, 80.0])
        self.assertEqual(len(result["labels"]), 2)

    def test_transfers_are_excluded(self):
        self.spend("-100.00", self.groceries, 5)
        transfer = self.spend("-500.00", self.groceries, 6)
        transfer.is_transfer = True
        transfer.save()

        result = analytics.spend_over_time(date(2026, 4, 1), date(2026, 4, 30))

        self.assertEqual(result["values"], [100.0])

    def test_income_is_excluded_from_spend(self):
        self.spend("-100.00", self.groceries, 5)
        make_transaction(
            self.checking,
            posted_on=date(2026, 4, 6),
            amount=Decimal("3000.00"),
            description_raw="PAYROLL",
            category=self.salary,
        )

        result = analytics.spend_over_time(date(2026, 4, 1), date(2026, 4, 30))

        self.assertEqual(result["values"], [100.0])

    def test_a_refund_against_an_expense_category_nets_against_the_purchase(self):
        self.spend("-100.00", self.groceries, 5)
        self.spend("30.00", self.groceries, 12)  # a return, same category

        result = analytics.spend_over_time(date(2026, 4, 1), date(2026, 4, 30))

        self.assertEqual(result["values"], [70.0])

    def test_a_positive_uncategorized_transaction_is_not_treated_as_a_refund(self):
        # Uncategorized is far more likely to be income the classifier
        # hasn't reached yet than a refund -- it must not net against spend.
        self.spend("-100.00", self.groceries, 5)
        make_transaction(
            self.checking,
            posted_on=date(2026, 4, 6),
            amount=Decimal("3000.00"),
            description_raw="UNCATEGORIZED DEPOSIT",
            category=None,
        )

        result = analytics.spend_over_time(date(2026, 4, 1), date(2026, 4, 30))

        self.assertEqual(result["values"], [100.0])

    def test_a_bucket_refunded_more_than_it_spent_floors_at_zero(self):
        self.spend("-20.00", self.groceries, 5)
        self.spend("50.00", self.groceries, 12)

        result = analytics.spend_over_time(date(2026, 4, 1), date(2026, 4, 30))

        self.assertEqual(result["values"], [0.0])

    def test_categories_roll_up_to_their_parent(self):
        self.spend("-100.00", self.groceries, 5)
        self.spend("-60.00", self.restaurants, 6)
        self.spend("-40.00", self.fuel, 7)

        result = analytics.spend_by_category(date(2026, 4, 1), date(2026, 4, 30))

        pairs = dict(zip(result["labels"], result["values"]))

        # Groceries and restaurants both live under Food.
        self.assertEqual(pairs["Food"], 160.0)
        self.assertEqual(pairs["Transportation"], 40.0)

    def test_a_category_refunded_more_than_it_spent_floors_at_zero_not_negative(self):
        self.spend("-20.00", self.groceries, 5)
        self.spend("50.00", self.groceries, 12)
        self.spend("-40.00", self.fuel, 7)

        result = analytics.spend_by_category(date(2026, 4, 1), date(2026, 4, 30))
        pairs = dict(zip(result["labels"], result["values"]))

        self.assertEqual(pairs["Food"], 0.0)
        self.assertEqual(pairs["Transportation"], 40.0)
        self.assertEqual(result["total"], 40.0)

    def test_categories_are_ranked_largest_first(self):
        self.spend("-40.00", self.fuel, 7)
        self.spend("-100.00", self.groceries, 5)

        result = analytics.spend_by_category(date(2026, 4, 1), date(2026, 4, 30))

        self.assertEqual(result["labels"][0], "Food")

    def test_a_long_tail_is_grouped_rather_than_listed(self):
        self.spend("-100.00", self.groceries, 5)
        self.spend("-40.00", self.fuel, 6)

        result = analytics.spend_by_category(
            date(2026, 4, 1), date(2026, 4, 30), limit=1
        )

        self.assertEqual(result["labels"], ["Food", "Everything else"])
        self.assertEqual(result["values"], [100.0, 40.0])

    def test_an_account_filter_narrows_the_series(self):
        self.spend("-100.00", self.groceries, 5, account=self.checking)
        self.spend("-60.00", self.groceries, 6, account=self.card)

        result = analytics.spend_over_time(
            date(2026, 4, 1), date(2026, 4, 30), account_ids=[self.card.pk]
        )

        self.assertEqual(result["values"], [60.0])

    def test_an_empty_window_returns_empty_series_not_an_error(self):
        result = analytics.spend_over_time(date(2020, 1, 1), date(2020, 12, 31))

        self.assertEqual(result["labels"], [])
        self.assertEqual(result["values"], [])


class IncomeAnalyticsTests(AnalyticsTestCase):
    def make_paycheck(self, day, gross="5000.00", net="3400.00", month=4):
        paycheck = Paycheck.objects.create(
            user=self.user,
            employer="Acme",
            pay_date=date(2026, month, day),
            gross=Decimal(gross),
            net=Decimal(net),
        )

        for kind, amount in [
            (DeductionKind.FEDERAL_TAX, "800.00"),
            (DeductionKind.FICA, "350.00"),
            (DeductionKind.RETIREMENT, "400.00"),
            (DeductionKind.INSURANCE, "50.00"),
        ]:
            PaycheckDeduction.objects.create(
                paycheck=paycheck, kind=kind, amount=Decimal(amount)
            )

        return paycheck

    def test_gross_and_net_are_bucketed_by_month(self):
        self.make_paycheck(15, month=3)
        self.make_paycheck(15, month=4)
        self.make_paycheck(30, month=4)

        result = analytics.income_over_time(date(2026, 3, 1), date(2026, 4, 30))

        self.assertEqual(result["gross"], [5000.0, 10000.0])
        self.assertEqual(result["net"], [3400.0, 6800.0])

    def test_retirement_is_reported_apart_from_tax(self):
        self.make_paycheck(15)

        result = analytics.income_over_time(date(2026, 4, 1), date(2026, 4, 30))

        # Retirement is still household money; tax is not.
        self.assertEqual(result["tax"], [1150.0])
        self.assertEqual(result["retained"], [400.0])
        self.assertEqual(result["other"], [50.0])

    def test_no_paychecks_reports_no_data_rather_than_zeroes(self):
        result = analytics.income_over_time(date(2026, 4, 1), date(2026, 4, 30))

        self.assertFalse(result["has_data"])

    def test_deposits_without_a_payslip_are_surfaced(self):
        # Otherwise the dashboard silently under-reports gross pay.
        make_transaction(
            self.checking,
            posted_on=date(2026, 4, 15),
            amount=Decimal("3400.00"),
            description_raw="ACME PAYROLL",
            category=self.salary,
        )

        unmatched = analytics.deposits_without_paychecks(
            date(2026, 4, 1), date(2026, 4, 30)
        )

        self.assertEqual(unmatched.count(), 1)

    def test_a_deposit_linked_to_a_paycheck_is_not_flagged(self):
        deposit = make_transaction(
            self.checking,
            posted_on=date(2026, 4, 15),
            amount=Decimal("3400.00"),
            description_raw="ACME PAYROLL",
            category=self.salary,
        )
        paycheck = self.make_paycheck(15)
        paycheck.deposit_transaction = deposit
        paycheck.save()

        unmatched = analytics.deposits_without_paychecks(
            date(2026, 4, 1), date(2026, 4, 30)
        )

        self.assertEqual(unmatched.count(), 0)


class NetIncomeAnalyticsTests(AnalyticsTestCase):
    """The primary income figure — every income-categorized deposit, no
    payslip required. This is what makes the Income dashboard work for a
    household member whose pay never gets a detailed payslip import."""

    def deposit(self, amount, day, category=None, month=4, **kwargs):
        return make_transaction(
            self.checking,
            posted_on=date(2026, month, day),
            amount=Decimal(amount),
            description_raw=f"DEPOSIT {month}-{day}",
            category=category if category is not None else self.salary,
            **kwargs,
        )

    def test_a_deposit_with_no_payslip_still_counts(self):
        self.deposit("3400.00", 15)

        result = analytics.net_income_over_time(date(2026, 4, 1), date(2026, 4, 30))

        self.assertEqual(result["values"], [3400.0])
        self.assertTrue(result["has_data"])

    def test_a_paycheck_linked_deposit_also_counts(self):
        # net_income_over_time reads transactions directly -- a linked
        # Paycheck record neither adds to nor is required for this total.
        deposit = self.deposit("3400.00", 15)
        paycheck = Paycheck.objects.create(
            user=self.user, employer="Acme", pay_date=date(2026, 4, 15),
            gross=Decimal("5000.00"), net=Decimal("3400.00"),
            deposit_transaction=deposit,
        )

        result = analytics.net_income_over_time(date(2026, 4, 1), date(2026, 4, 30))

        self.assertEqual(result["values"], [3400.0])

    def test_transfers_are_excluded(self):
        transfer = self.deposit("500.00", 6)
        transfer.is_transfer = True
        transfer.save()

        result = analytics.net_income_over_time(date(2026, 4, 1), date(2026, 4, 30))

        self.assertEqual(result["values"], [])

    def test_spend_is_excluded(self):
        self.deposit("-100.00", 5, category=self.groceries)

        result = analytics.net_income_over_time(date(2026, 4, 1), date(2026, 4, 30))

        self.assertEqual(result["values"], [])

    def test_an_uncategorized_deposit_is_not_assumed_to_be_income(self):
        # Symmetric with spend_filter()'s caution in the other direction: an
        # uncategorized positive amount could just as easily be an
        # uncategorized refund.
        make_transaction(
            self.checking,
            posted_on=date(2026, 4, 15),
            amount=Decimal("3400.00"),
            description_raw="UNCATEGORIZED DEPOSIT",
            category=None,
        )

        result = analytics.net_income_over_time(date(2026, 4, 1), date(2026, 4, 30))

        self.assertEqual(result["values"], [])

    def test_no_income_reports_no_data_rather_than_a_zero(self):
        result = analytics.net_income_over_time(date(2026, 4, 1), date(2026, 4, 30))

        self.assertFalse(result["has_data"])
        self.assertEqual(result["values"], [])


class BalanceHistoryTests(AnalyticsTestCase):
    def snapshot(self, account, day, amount):
        return AccountBalanceSnapshot.objects.create(
            account=account, as_of=day, current=Decimal(amount)
        )

    def test_balances_carry_forward_across_quiet_days(self):
        # A mortgage reports monthly; without carry-forward the chart would be
        # disconnected dots.
        today = household_today()
        self.snapshot(self.checking, today - timedelta(days=10), "1000.00")
        self.snapshot(self.checking, today - timedelta(days=2), "1200.00")

        history = analytics.balance_history(
            start=today - timedelta(days=12), end=today
        )
        values = history["series"][0]["values"]

        self.assertIsNone(values[0])
        self.assertEqual(values[3], 1000.0)
        self.assertEqual(values[-1], 1200.0)

    def test_a_balance_from_before_the_window_seeds_the_series(self):
        # Otherwise the chart starts at nothing and appears to plunge on day one.
        today = household_today()
        self.snapshot(self.checking, today - timedelta(days=60), "900.00")

        history = analytics.balance_history(start=today - timedelta(days=5), end=today)

        self.assertEqual(history["series"][0]["values"][0], 900.0)

    def test_net_worth_is_none_before_anything_reports(self):
        today = household_today()
        self.snapshot(self.checking, today, "1000.00")

        history = analytics.net_worth_history(start=today - timedelta(days=3), end=today)

        # A zero here would draw a cliff to the axis and read as being broke.
        self.assertIsNone(history["values"][0])
        self.assertEqual(history["values"][-1], 1000.0)

    def test_accounts_without_history_are_omitted(self):
        today = household_today()
        self.snapshot(self.checking, today, "1000.00")

        history = analytics.balance_history(start=today - timedelta(days=3), end=today)

        self.assertEqual(len(history["series"]), 1)

    def test_net_worth_sums_the_carried_forward_series(self):
        today = household_today()
        self.snapshot(self.checking, today - timedelta(days=1), "1000.00")
        self.snapshot(self.card, today - timedelta(days=1), "-400.00")

        history = analytics.net_worth_history(
            start=today - timedelta(days=2), end=today
        )

        self.assertEqual(history["values"][-1], 600.0)

    def test_filtering_by_account_type(self):
        today = household_today()
        self.snapshot(self.checking, today, "1000.00")
        self.snapshot(self.card, today, "-400.00")

        history = analytics.balance_history(
            start=today - timedelta(days=1),
            end=today,
            account_types=[AccountType.CREDIT_CARD],
        )

        self.assertEqual([s["label"] for s in history["series"]], ["Card"])
        self.assertTrue(history["series"][0]["is_liability"])


class SnapshotCommandTests(AnalyticsTestCase):
    def test_balances_are_recorded_for_today(self):
        self.checking.current_balance = Decimal("4200.00")
        self.checking.save()

        call_command("snapshot_balances", verbosity=0)

        snapshot = AccountBalanceSnapshot.objects.get(account=self.checking)
        self.assertEqual(snapshot.as_of, household_today())
        self.assertEqual(snapshot.current, Decimal("4200.00"))

    def test_accounts_without_a_balance_are_skipped(self):
        call_command("snapshot_balances", verbosity=0)

        self.assertEqual(AccountBalanceSnapshot.objects.count(), 0)

    def test_running_twice_overwrites_rather_than_stacking(self):
        self.checking.current_balance = Decimal("4200.00")
        self.checking.save()

        call_command("snapshot_balances", verbosity=0)
        self.checking.current_balance = Decimal("4300.00")
        self.checking.save()
        call_command("snapshot_balances", verbosity=0)

        self.assertEqual(AccountBalanceSnapshot.objects.count(), 1)
        self.assertEqual(
            AccountBalanceSnapshot.objects.get().current, Decimal("4300.00")
        )


class ChartsDashboardRenderTests(AnalyticsTestCase):
    def setUp(self):
        super().setUp()
        self.sign_in()

    def test_charts_page_renders_with_spend_data(self):
        # Dated today rather than a fixed day-of-month, which could fall
        # outside the range when the test runs early in a month.
        make_transaction(
            self.checking,
            posted_on=household_today(),
            amount=Decimal("-100.00"),
            description_raw="MARIANOS",
            category=self.groceries,
        )

        response = self.client.get(reverse("finance:charts"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "spend-over-time")
        self.assertContains(response, "spend-by-category-over-time")

    def test_spend_over_time_offers_a_by_category_toggle_with_its_own_data(self):
        # The stacked view reuses the same per-category series the "Spend by
        # category, over time" line chart is built from, but needs its own
        # json_script id so it renders even when that other section is
        # deselected (see test_a_deselected_section_does_not_render below).
        make_transaction(
            self.checking,
            posted_on=household_today(),
            amount=Decimal("-100.00"),
            description_raw="MARIANOS",
            category=self.groceries,
        )

        response = self.client.get(reverse("finance:charts"))
        body = response.content.decode()

        self.assertIn('data-chart-toggle="spend-over-time"', body)
        self.assertIn('data-source-stacked="spend-over-time-by-category"', body)
        self.assertIn('id="spend-over-time-by-category"', body)

    def test_charts_page_handles_no_data(self):
        response = self.client.get(reverse("finance:charts"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nothing to chart")

    def test_income_section_shows_net_income_with_a_payslip_note(self):
        # No Paycheck record at all -- net income still renders from the
        # deposit alone, with a low-key pointer toward payslip import rather
        # than the old empty state gated on payslip data existing.
        make_transaction(
            self.checking,
            posted_on=household_today(),
            amount=Decimal("3400.00"),
            description_raw="ACME PAYROLL",
            category=self.salary,
        )

        response = self.client.get(reverse("finance:charts"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "net-income")
        self.assertContains(response, "no payslip imported")

    def test_net_cash_flow_section_renders(self):
        make_transaction(
            self.checking,
            posted_on=household_today(),
            amount=Decimal("3400.00"),
            description_raw="ACME PAYROLL",
            category=self.salary,
        )
        make_transaction(
            self.checking,
            posted_on=household_today(),
            amount=Decimal("-100.00"),
            description_raw="MARIANOS",
            category=self.groceries,
        )

        response = self.client.get(reverse("finance:charts"))

        self.assertContains(response, "cash-flow")

    def test_savings_section_renders(self):
        AccountBalanceSnapshot.objects.create(
            account=self.checking,
            as_of=household_today(),
            current=Decimal("1000.00"),
        )

        response = self.client.get(reverse("finance:charts"))

        self.assertEqual(response.status_code, 200)

    def test_the_range_filter_is_honoured(self):
        response = self.client.get(reverse("finance:charts"), {"range": "3m"})

        self.assertEqual(response.context["selected_range"], "3m")
        span = (response.context["end"] - response.context["start"]).days
        self.assertEqual(span, 90)

    def test_the_range_buttons_form_does_not_duplicate_the_range_param(self):
        # Regression: the hidden input carrying the current range for the
        # grain form used to live in the *same* form as the range buttons,
        # so clicking any range button also submitted the old range via
        # that hidden input -- two values for one name, and Django's
        # QueryDict silently keeps the last one, pinning the range to
        # whatever it already was no matter which button was clicked.
        response = self.client.get(
            reverse("finance:charts"), {"range": "12m", "grain": "monthly"}
        )
        body = response.content.decode()

        # Anchored on a range button rather than "the first <form>" -- the
        # header's own sign-out form appears earlier in the page.
        range_button_index = body.index('value="3m"')
        range_form_start = body.rindex("<form", 0, range_button_index)
        range_form_end = body.index("</form>", range_button_index)
        range_form = body[range_form_start:range_form_end]

        self.assertEqual(range_form.count('name="range"'), len(RANGE_CHOICES))
        self.assertNotIn('type="hidden" name="range"', range_form)

    def test_switching_the_range_actually_changes_it(self):
        self.client.get(reverse("finance:charts"), {"range": "12m", "grain": "monthly"})
        response = self.client.get(
            reverse("finance:charts"), {"range": "3m", "grain": "monthly"}
        )

        self.assertEqual(response.context["selected_range"], "3m")

    def test_an_unknown_grain_falls_back_to_monthly(self):
        response = self.client.get(reverse("finance:charts"), {"grain": "hourly"})

        self.assertEqual(response.context["selected_grain"], "monthly")

    def test_a_grain_unavailable_for_the_range_falls_back_to_monthly(self):
        # Annually needs a full year to mean anything; a 3-month range asking
        # for it should not silently draw a single misleading bar.
        response = self.client.get(
            reverse("finance:charts"), {"range": "3m", "grain": "annually"}
        )

        self.assertEqual(response.context["selected_grain"], "monthly")

    def test_quarterly_is_offered_once_the_range_covers_it(self):
        response = self.client.get(reverse("finance:charts"), {"range": "12m"})

        self.assertIn(
            "quarterly", dict(response.context["grain_choices"])
        )

    def test_quarterly_is_not_offered_for_a_short_range(self):
        response = self.client.get(reverse("finance:charts"), {"range": "3m"})

        self.assertNotIn(
            "quarterly", dict(response.context["grain_choices"])
        )

    def test_charts_page_is_gated_like_everything_else(self):
        self.client.logout()

        self.assertEqual(self.client.get(reverse("finance:charts")).status_code, 403)

    def test_a_deselected_section_does_not_render(self):
        from finance.models import UserPreference

        make_transaction(
            self.checking,
            posted_on=household_today(),
            amount=Decimal("-100.00"),
            description_raw="MARIANOS",
            category=self.groceries,
        )

        preference = UserPreference.for_user(self.user)
        preference.chart_sections = ["spend_over_time"]
        preference.save()

        response = self.client.get(reverse("finance:charts"))

        self.assertContains(response, "spend-over-time")
        self.assertNotContains(response, "spend-by-category-over-time")
        # The toggle's own stacked data isn't tied to that other section's
        # visibility -- it renders as long as spend_over_time itself does.
        self.assertContains(response, "spend-over-time-by-category")

    def test_sections_render_in_the_saved_order(self):
        from finance.models import UserPreference

        preference = UserPreference.for_user(self.user)
        preference.chart_sections = ["net_cash_flow", "spend_over_time"]
        preference.save()

        response = self.client.get(reverse("finance:charts"))

        self.assertEqual(
            response.context["chart_sections"], ["net_cash_flow", "spend_over_time"]
        )

    def test_large_transactions_and_recurring_expenses_sections_render(self):
        self.spend("-900.00", self.groceries, 5)
        for month in (2, 3, 4):
            make_transaction(
                self.checking, posted_on=date(2026, month, 6), amount=Decimal("-15.99"),
                description_raw="NETFLIX", merchant="Netflix", category=self.groceries,
            )

        response = self.client.get(reverse("finance:charts"), {"range": "6m"})

        self.assertContains(response, "Largest transactions")
        self.assertContains(response, "recurring-expenses")

    def test_balances_over_time_replaces_the_old_savings_and_debt_charts(self):
        AccountBalanceSnapshot.objects.create(
            account=self.checking, as_of=household_today(), current=Decimal("1000.00")
        )

        response = self.client.get(reverse("finance:charts"))

        self.assertContains(response, "balances-over-time")
        self.assertNotContains(response, "savings-series")
        self.assertNotContains(response, "debt-series")


class ChartHideShowTests(AnalyticsTestCase):
    def setUp(self):
        super().setUp()
        self.sign_in()
        make_transaction(
            self.checking, posted_on=household_today(), amount=Decimal("-100.00"),
            description_raw="MARIANOS", category=self.groceries,
        )

    def test_hiding_a_chart_removes_it_from_the_page_and_saves_the_preference(self):
        from finance.models import UserPreference

        response = self.client.post(
            reverse("finance:charts"),
            {"action": "hide_section", "section": "spend_over_time"},
        )

        self.assertRedirects(response, reverse("finance:charts"))
        preference = UserPreference.for_user(self.user)
        self.assertNotIn("spend_over_time", preference.chart_sections)

        page = self.client.get(reverse("finance:charts"))
        self.assertNotIn("spend_over_time", page.context["chart_sections"])

    def test_a_hidden_chart_appears_in_the_hidden_charts_tray(self):
        self.client.post(
            reverse("finance:charts"),
            {"action": "hide_section", "section": "spend_over_time"},
        )

        response = self.client.get(reverse("finance:charts"))

        self.assertIn(
            "spend_over_time", dict(response.context["hidden_sections"])
        )
        self.assertContains(response, "Hidden charts")

    def test_showing_a_hidden_chart_appends_it_to_the_end(self):
        from finance.models import UserPreference

        preference = UserPreference.for_user(self.user)
        preference.chart_sections = ["net_cash_flow", "spend_over_time"]
        preference.save()

        self.client.post(
            reverse("finance:charts"),
            {"action": "show_section", "section": "spend_over_time"},
        )
        # Re-hide something already visible first, so re-showing it proves
        # the "goes to the end" behaviour rather than "stayed in place".
        self.client.post(
            reverse("finance:charts"),
            {"action": "hide_section", "section": "net_cash_flow"},
        )
        self.client.post(
            reverse("finance:charts"),
            {"action": "show_section", "section": "net_cash_flow"},
        )

        preference.refresh_from_db()
        self.assertEqual(
            preference.chart_sections, ["spend_over_time", "net_cash_flow"]
        )

    def test_hide_and_show_are_gated_like_everything_else(self):
        self.client.logout()

        response = self.client.post(
            reverse("finance:charts"),
            {"action": "hide_section", "section": "spend_over_time"},
        )

        self.assertEqual(response.status_code, 403)

    def test_hiding_preserves_the_active_range_filter(self):
        response = self.client.post(
            f"{reverse('finance:charts')}?range=3m",
            {"action": "hide_section", "section": "spend_over_time"},
        )

        self.assertRedirects(response, f"{reverse('finance:charts')}?range=3m")


class BalancesOverTimeFilterTests(AnalyticsTestCase):
    def setUp(self):
        super().setUp()
        self.sign_in()

    def test_the_filter_stays_visible_even_when_the_selection_has_no_history(self):
        from finance.models import AccountBalanceSnapshot

        AccountBalanceSnapshot.objects.create(
            account=self.checking, as_of=household_today(), current=Decimal("1000.00")
        )

        # Filtering down to an account with no snapshots at all must not
        # also hide the filter control -- that would be a dead end.
        response = self.client.get(
            reverse("finance:charts"), {"balances_account": [self.card.pk]}
        )

        self.assertContains(response, "Balances over time")
        self.assertFalse(response.context["balances_over_time_has_data"])
        self.assertTrue(response.context["balances_over_time_available"])

    def test_the_account_filter_is_a_plain_inline_select_not_a_popover(self):
        # Styled the same way as Largest Transactions' filters: a plain
        # <select> inline in the section body, not a click-to-open overlay.
        AccountBalanceSnapshot.objects.create(
            account=self.checking, as_of=household_today(), current=Decimal("1000.00")
        )

        response = self.client.get(reverse("finance:charts"))
        body = response.content.decode()

        self.assertIn('name="balances_account" multiple', body)
        self.assertNotIn("<details", body)

    def test_selecting_two_accounts_narrows_the_series_to_both(self):
        AccountBalanceSnapshot.objects.create(
            account=self.checking, as_of=household_today(), current=Decimal("1000.00")
        )
        AccountBalanceSnapshot.objects.create(
            account=self.card, as_of=household_today(), current=Decimal("-200.00")
        )

        response = self.client.get(
            reverse("finance:charts"),
            {"balances_account": [self.checking.pk, self.card.pk]},
        )

        self.assertEqual(
            set(response.context["selected_balances_accounts"]),
            {self.checking.pk, self.card.pk},
        )
        self.assertTrue(response.context["balances_over_time_has_data"])


class SpendByCategoryOverTimeAnalyticsTests(AnalyticsTestCase):
    def test_each_category_gets_its_own_aligned_series(self):
        self.spend("-100.00", self.groceries, 5, month=3)
        self.spend("-40.00", self.fuel, 6, month=4)

        result = analytics.spend_by_category_over_time(
            date(2026, 3, 1), date(2026, 4, 30), grain="monthly"
        )

        by_label = {series["label"]: series["values"] for series in result["series"]}

        self.assertEqual(by_label["Food"], [100.0, 0.0])
        self.assertEqual(by_label["Transportation"], [0.0, 40.0])

    def test_a_long_tail_is_grouped_as_everything_else(self):
        self.spend("-100.00", self.groceries, 5, month=4)
        self.spend("-40.00", self.fuel, 6, month=4)

        result = analytics.spend_by_category_over_time(
            date(2026, 4, 1), date(2026, 4, 30), grain="monthly", limit=1
        )

        labels = [series["label"] for series in result["series"]]
        self.assertEqual(labels, ["Food", "Everything else"])

    def test_an_empty_window_still_reports_no_data(self):
        result = analytics.spend_by_category_over_time(
            date(2020, 1, 1), date(2020, 3, 31)
        )

        self.assertFalse(result["has_data"])
        self.assertEqual(result["series"], [])


class LargestTransactionsAnalyticsTests(AnalyticsTestCase):
    def test_largest_outflows_ranked_first(self):
        self.spend("-40.00", self.groceries, 5)
        self.spend("-900.00", self.groceries, 6)
        self.spend("-15.00", self.fuel, 7)

        result = analytics.largest_transactions(date(2026, 4, 1), date(2026, 4, 30))

        amounts = [t.amount for t in result["transactions"]]
        self.assertEqual(amounts, [Decimal("-900.00"), Decimal("-40.00"), Decimal("-15.00")])
        self.assertTrue(result["has_data"])

    def test_refunds_are_not_treated_as_large_expenses(self):
        self.spend("-40.00", self.groceries, 5)
        self.spend("500.00", self.groceries, 12)  # a big refund, same category

        result = analytics.largest_transactions(date(2026, 4, 1), date(2026, 4, 30))

        self.assertEqual(len(result["transactions"]), 1)
        self.assertEqual(result["transactions"][0].amount, Decimal("-40.00"))

    def test_respects_the_limit(self):
        for day in range(1, 6):
            self.spend(f"-{day * 10}.00", self.groceries, day)

        result = analytics.largest_transactions(date(2026, 4, 1), date(2026, 4, 30), limit=2)

        self.assertEqual(len(result["transactions"]), 2)

    def test_an_empty_window_reports_no_data(self):
        result = analytics.largest_transactions(date(2020, 1, 1), date(2020, 3, 31))

        self.assertFalse(result["has_data"])
        self.assertEqual(result["transactions"], [])


class RecurringExpensesAnalyticsTests(AnalyticsTestCase):
    def merchant_txn(self, merchant, amount, day, month=4):
        return make_transaction(
            self.checking,
            posted_on=date(2026, month, day),
            amount=Decimal(amount),
            description_raw=f"{merchant} PURCHASE",
            merchant=merchant,
            category=self.groceries,
        )

    def test_a_merchant_recurring_across_periods_gets_its_own_line(self):
        self.merchant_txn("Netflix", "-15.99", 5, month=2)
        self.merchant_txn("Netflix", "-15.99", 5, month=3)
        self.merchant_txn("Netflix", "-17.99", 5, month=4)

        result = analytics.recurring_expenses_over_time(
            date(2026, 2, 1), date(2026, 4, 30), grain="monthly", min_occurrences=3
        )

        by_label = {series["label"]: series["values"] for series in result["series"]}
        self.assertEqual(by_label["Netflix"], [15.99, 15.99, 17.99])

    def test_a_merchant_seen_only_once_is_not_recurring(self):
        self.merchant_txn("One-off Store", "-40.00", 5, month=4)

        result = analytics.recurring_expenses_over_time(
            date(2026, 2, 1), date(2026, 4, 30), grain="monthly", min_occurrences=3
        )

        self.assertEqual(result["series"], [])
        self.assertFalse(result["has_data"])

    def test_falls_back_to_description_when_no_merchant_is_set(self):
        for month in (2, 3, 4):
            make_transaction(
                self.checking, posted_on=date(2026, month, 5), amount=Decimal("-9.99"),
                description_raw="ACME WIDGET CO", merchant="", category=self.groceries,
            )

        result = analytics.recurring_expenses_over_time(
            date(2026, 2, 1), date(2026, 4, 30), grain="monthly", min_occurrences=3
        )

        labels = [series["label"] for series in result["series"]]
        self.assertEqual(labels, ["ACME WIDGET CO"])

    def test_ranked_by_total_spend_and_capped_to_the_limit(self):
        for month in (2, 3, 4):
            self.merchant_txn("Big Spender", "-200.00", 5, month=month)
            self.merchant_txn("Small Spender", "-5.00", 6, month=month)

        result = analytics.recurring_expenses_over_time(
            date(2026, 2, 1), date(2026, 4, 30), grain="monthly", min_occurrences=3, limit=1
        )

        labels = [series["label"] for series in result["series"]]
        self.assertEqual(labels, ["Big Spender"])

    def test_an_empty_window_reports_no_data(self):
        result = analytics.recurring_expenses_over_time(date(2020, 1, 1), date(2020, 3, 31))

        self.assertFalse(result["has_data"])


class NetCashFlowAnalyticsTests(AnalyticsTestCase):
    def test_income_minus_spend_per_period(self):
        self.deposit_income("3000.00", 6, month=4)
        self.spend("-1200.00", self.groceries, 5, month=4)

        result = analytics.net_cash_flow_over_time(
            date(2026, 4, 1), date(2026, 4, 30), grain="monthly"
        )

        self.assertEqual(result["values"], [1800.0])
        self.assertTrue(result["has_data"])

    def test_a_period_with_only_spend_is_negative(self):
        self.spend("-500.00", self.groceries, 5, month=4)

        result = analytics.net_cash_flow_over_time(
            date(2026, 4, 1), date(2026, 4, 30), grain="monthly"
        )

        self.assertEqual(result["values"], [-500.0])

    def test_buckets_align_even_when_only_one_side_has_data(self):
        self.deposit_income("1000.00", 6, month=3)
        self.spend("-200.00", self.groceries, 5, month=4)

        result = analytics.net_cash_flow_over_time(
            date(2026, 3, 1), date(2026, 4, 30), grain="monthly"
        )

        self.assertEqual(result["values"], [1000.0, -200.0])

    def test_an_empty_window_reports_no_data(self):
        result = analytics.net_cash_flow_over_time(date(2020, 1, 1), date(2020, 3, 31))

        self.assertFalse(result["has_data"])

    def deposit_income(self, amount, day, month=4):
        return make_transaction(
            self.checking,
            posted_on=date(2026, month, day),
            amount=Decimal(amount),
            description_raw=f"DEPOSIT {month}-{day}",
            category=self.salary,
        )


class QuarterlyAndAnnualGrainAnalyticsTests(AnalyticsTestCase):
    def test_spend_over_time_buckets_by_quarter(self):
        self.spend("-100.00", self.groceries, 5, month=1)
        self.spend("-40.00", self.groceries, 6, month=5)

        result = analytics.spend_over_time(
            date(2026, 1, 1), date(2026, 6, 30), grain="quarterly"
        )

        self.assertEqual(result["labels"], ["Q1 2026", "Q2 2026"])
        self.assertEqual(result["values"], [100.0, 40.0])

    def test_net_income_over_time_buckets_by_year(self):
        self.deposit(3000, 6, month=1)
        self.deposit(1000, 6, month=6)

        result = analytics.net_income_over_time(
            date(2026, 1, 1), date(2026, 12, 31), grain="annually"
        )

        self.assertEqual(result["labels"], ["2026"])
        self.assertEqual(result["values"], [4000.0])

    def deposit(self, amount, day, month=4):
        return make_transaction(
            self.checking,
            posted_on=date(2026, month, day),
            amount=Decimal(str(amount)),
            description_raw=f"DEPOSIT {month}-{day}",
            category=self.salary,
        )


class UncategorizedSpendTests(TestCase):
    """Requiring an expense category silently dropped spend from every total."""

    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)

        self.institution = make_institution()
        self.account = make_account(self.institution, name="Checking")
        self.groceries = Category.objects.get(slug="food-groceries")

        Transaction.objects.create(
            account=self.account, posted_on=date(2026, 4, 10),
            amount=Decimal("-100.00"), description_raw="CATEGORIZED",
            category=self.groceries, fingerprint="a",
        )
        Transaction.objects.create(
            account=self.account, posted_on=date(2026, 4, 11),
            amount=Decimal("-250.00"), description_raw="NOT YET CATEGORIZED",
            category=None, fingerprint="b",
        )

    def test_the_total_matches_the_money_that_actually_left(self):
        self.assertEqual(
            analytics.spend_over_time(date(2026, 4, 1), date(2026, 4, 30))["values"],
            [350.0],
        )

    def test_uncategorized_spend_gets_its_own_visible_slice(self):
        result = analytics.spend_by_category(date(2026, 4, 1), date(2026, 4, 30))
        pairs = dict(zip(result["labels"], result["values"]))

        self.assertEqual(pairs["Not yet categorized"], 250.0)
        self.assertEqual(result["total"], 350.0)

    def test_income_and_transfers_are_still_excluded(self):
        salary = Category.objects.get(slug="income-salary")

        Transaction.objects.create(
            account=self.account, posted_on=date(2026, 4, 12),
            amount=Decimal("3000.00"), description_raw="PAYROLL",
            category=salary, fingerprint="c",
        )
        transfer = Transaction.objects.create(
            account=self.account, posted_on=date(2026, 4, 13),
            amount=Decimal("-500.00"), description_raw="TO SAVINGS",
            category=None, fingerprint="d",
        )
        transfer.is_transfer = True
        transfer.save()

        self.assertEqual(
            analytics.spend_over_time(date(2026, 4, 1), date(2026, 4, 30))["values"],
            [350.0],
        )
