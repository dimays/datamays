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

    def test_a_positive_uncategorised_transaction_is_not_treated_as_a_refund(self):
        # Uncategorised is far more likely to be income the classifier
        # hasn't reached yet than a refund -- it must not net against spend.
        self.spend("-100.00", self.groceries, 5)
        make_transaction(
            self.checking,
            posted_on=date(2026, 4, 6),
            amount=Decimal("3000.00"),
            description_raw="UNCATEGORISED DEPOSIT",
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


class DashboardRenderTests(AnalyticsTestCase):
    def setUp(self):
        super().setUp()
        self.sign_in()

    def test_spend_dashboard_renders_with_data(self):
        # Dated today rather than a fixed day-of-month, which could fall
        # outside the range when the test runs early in a month.
        make_transaction(
            self.checking,
            posted_on=household_today(),
            amount=Decimal("-100.00"),
            description_raw="MARIANOS",
            category=self.groceries,
        )

        response = self.client.get(reverse("finance:spend"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "spend-over-time")

    def test_spend_dashboard_handles_no_data(self):
        response = self.client.get(reverse("finance:spend"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No spending recorded")

    def test_income_dashboard_warns_when_payslips_are_missing(self):
        make_transaction(
            self.checking,
            posted_on=household_today(),
            amount=Decimal("3400.00"),
            description_raw="ACME PAYROLL",
            category=self.salary,
        )

        response = self.client.get(reverse("finance:income"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "no payslip imported")

    def test_savings_dashboard_renders(self):
        AccountBalanceSnapshot.objects.create(
            account=self.checking,
            as_of=household_today(),
            current=Decimal("1000.00"),
        )

        response = self.client.get(reverse("finance:savings"))

        self.assertEqual(response.status_code, 200)

    def test_the_range_filter_is_honoured(self):
        response = self.client.get(reverse("finance:spend"), {"range": "3m"})

        self.assertEqual(response.context["selected_range"], "3m")
        span = (response.context["end"] - response.context["start"]).days
        self.assertEqual(span, 90)

    def test_an_unknown_grain_falls_back_to_monthly(self):
        response = self.client.get(reverse("finance:spend"), {"grain": "hourly"})

        self.assertEqual(response.context["selected_grain"], "monthly")

    def test_dashboards_are_gated_like_everything_else(self):
        self.client.logout()

        for name in ["spend", "income", "savings"]:
            with self.subTest(dashboard=name):
                self.assertEqual(self.client.get(reverse(f"finance:{name}")).status_code, 403)


class UncategorisedSpendTests(TestCase):
    """Requiring an expense category silently dropped spend from every total."""

    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)

        self.institution = make_institution()
        self.account = make_account(self.institution, name="Checking")
        self.groceries = Category.objects.get(slug="food-groceries")

        Transaction.objects.create(
            account=self.account, posted_on=date(2026, 4, 10),
            amount=Decimal("-100.00"), description_raw="CATEGORISED",
            category=self.groceries, fingerprint="a",
        )
        Transaction.objects.create(
            account=self.account, posted_on=date(2026, 4, 11),
            amount=Decimal("-250.00"), description_raw="NOT YET CATEGORISED",
            category=None, fingerprint="b",
        )

    def test_the_total_matches_the_money_that_actually_left(self):
        self.assertEqual(
            analytics.spend_over_time(date(2026, 4, 1), date(2026, 4, 30))["values"],
            [350.0],
        )

    def test_uncategorised_spend_gets_its_own_visible_slice(self):
        result = analytics.spend_by_category(date(2026, 4, 1), date(2026, 4, 30))
        pairs = dict(zip(result["labels"], result["values"]))

        self.assertEqual(pairs["Not yet categorised"], 250.0)
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
