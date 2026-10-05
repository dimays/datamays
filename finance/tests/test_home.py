"""The homepage: what each widget shows, and what it deliberately hides."""

from datetime import date, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from finance.dates import household_today
from finance.models import (
    AccountConnection,
    AccountType,
    Budget,
    BudgetPeriod,
    Category,
    UserPreference,
)
from finance.services.widgets import build_homepage

from .factories import make_account, make_institution, make_transaction
from .test_access import make_user


class HomepageTestCase(TestCase):
    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)

        self.user = make_user("david", with_device=True)
        self.institution = make_institution()
        self.groceries = Category.objects.get(slug="food-groceries")

        # Synced accounts carry a connection; that is what distinguishes them
        # from manual ones for staleness purposes.
        self.connection = AccountConnection.objects.create(
            institution=self.institution, label="Byline", access_secret="x"
        )

        self.checking = make_account(
            self.institution,
            name="Checking",
            connection=self.connection,
            current_balance=Decimal("4200.00"),
            balance_as_of=timezone.now(),
        )
        self.card = make_account(
            self.institution,
            name="Card",
            account_type=AccountType.CREDIT_CARD,
            connection=self.connection,
            current_balance=Decimal("-1350.00"),
            balance_as_of=timezone.now(),
        )

    def sign_in(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["otp_device_id"] = TOTPDevice.objects.get(user=self.user).persistent_id
        session.save()

    def widget(self, slug):
        return next(
            (w for w in build_homepage(self.user)["widgets"] if w["slug"] == slug), None
        )


class BalanceWidgetTests(HomepageTestCase):
    def test_balances_are_listed_with_a_net_total(self):
        preference = UserPreference.for_user(self.user)
        preference.homepage_widgets = ["balances"]
        preference.save()

        data = self.widget("balances")["data"]

        self.assertEqual(len(data["accounts"]), 2)
        self.assertEqual(data["total"], Decimal("2850.00"))

    def test_a_debt_carries_its_negative_sign_into_the_widget_data(self):
        # The template is what turns this into "-$1,350.00"; this just
        # confirms the widget hands it the real signed value to render.
        preference = UserPreference.for_user(self.user)
        preference.homepage_widgets = ["balances"]
        preference.save()

        card = next(
            a for a in self.widget("balances")["data"]["accounts"] if a.name == "Card"
        )

        self.assertEqual(card.display_balance, Decimal("-1350.00"))

    def test_a_stale_balance_is_flagged(self):
        # A quietly failing sync is the worst failure: the numbers look fine,
        # they are just old.
        self.checking.balance_as_of = timezone.now() - timedelta(days=5)
        self.checking.save()

        preference = UserPreference.for_user(self.user)
        preference.homepage_widgets = ["balances"]
        preference.save()

        self.assertEqual(len(self.widget("balances")["data"]["stale"]), 1)

    def test_manual_accounts_are_never_flagged_as_stale(self):
        manual = make_account(
            self.institution,
            name="Whole Life Policy",
            account_type=AccountType.INSURANCE,
            current_balance=Decimal("18000.00"),
        )

        preference = UserPreference.for_user(self.user)
        preference.homepage_widgets = ["balances"]
        preference.save()

        stale_names = {a.name for a in self.widget("balances")["data"]["stale"]}
        self.assertNotIn(manual.name, stale_names)

    def test_an_account_filter_narrows_the_widget(self):
        preference = UserPreference.for_user(self.user)
        preference.homepage_widgets = ["balances"]
        preference.homepage_account_ids = [self.checking.pk]
        preference.save()

        self.assertEqual(len(self.widget("balances")["data"]["accounts"]), 1)


class NetWorthWidgetTests(HomepageTestCase):
    def test_assets_and_debts_are_split_and_summed(self):
        preference = UserPreference.for_user(self.user)
        preference.homepage_widgets = ["net_worth"]
        preference.save()

        data = self.widget("net_worth")["data"]

        self.assertEqual(data["assets"], Decimal("4200.00"))
        # Reported as a magnitude, since the card is labelled "Debts".
        self.assertEqual(data["liabilities"], Decimal("1350.00"))
        self.assertEqual(data["total"], Decimal("2850.00"))

    def test_excluded_accounts_are_left_out(self):
        self.card.include_in_net_worth = False
        self.card.save()

        preference = UserPreference.for_user(self.user)
        preference.homepage_widgets = ["net_worth"]
        preference.save()

        self.assertEqual(self.widget("net_worth")["data"]["total"], Decimal("4200.00"))


class BudgetWidgetTests(HomepageTestCase):
    def make_period(self, name, actual, target="800.00"):
        today = household_today()
        budget = Budget.objects.create(name=name, amount=Decimal(target))
        budget.categories.set([self.groceries])

        return BudgetPeriod.objects.create(
            budget=budget,
            period_start=today.replace(day=1),
            period_end=today.replace(day=28),
            target_amount=Decimal(target),
            actual_amount=Decimal(actual),
        )

    def test_the_worst_pace_sorts_first(self):
        self.make_period("Comfortable", "50.00")
        self.make_period("Blown", "900.00")

        preference = UserPreference.for_user(self.user)
        preference.homepage_widgets = ["budgets"]
        preference.save()

        rows = self.widget("budgets")["data"]["rows"]

        # The budget most at risk is the one worth seeing at a checkout.
        self.assertEqual(rows[0]["budget"].name, "Blown")

    def test_over_budget_periods_are_called_out(self):
        self.make_period("Blown", "900.00")

        preference = UserPreference.for_user(self.user)
        preference.homepage_widgets = ["budgets"]
        preference.save()

        self.assertEqual(len(self.widget("budgets")["data"]["over"]), 1)

    def test_only_the_current_period_is_shown(self):
        budget = Budget.objects.create(name="Old", amount=Decimal("800"))
        budget.categories.set([self.groceries])
        BudgetPeriod.objects.create(
            budget=budget,
            period_start=date(2020, 1, 1),
            period_end=date(2020, 1, 31),
            target_amount=Decimal("800"),
            actual_amount=Decimal("100"),
        )

        preference = UserPreference.for_user(self.user)
        preference.homepage_widgets = ["budgets"]
        preference.save()

        self.assertEqual(self.widget("budgets")["data"]["rows"], [])


class RecentTransactionsWidgetTests(HomepageTestCase):
    def test_transfers_are_excluded(self):
        make_transaction(self.checking, description_raw="GROCERIES")
        transfer = make_transaction(
            self.checking,
            amount=Decimal("-500.00"),
            description_raw="TO SAVINGS",
            posted_on=date(2026, 4, 16),
        )
        transfer.is_transfer = True
        transfer.save()

        preference = UserPreference.for_user(self.user)
        preference.homepage_widgets = ["recent_transactions"]
        preference.save()

        descriptions = [
            t.description_raw for t in self.widget("recent_transactions")["data"]["transactions"]
        ]

        self.assertIn("GROCERIES", descriptions)
        self.assertNotIn("TO SAVINGS", descriptions)

    def test_the_count_honours_the_preference(self):
        for day in range(1, 12):
            make_transaction(
                self.checking,
                posted_on=date(2026, 4, day),
                amount=Decimal(f"-{day}.00"),
                description_raw=f"SPEND {day}",
            )

        preference = UserPreference.for_user(self.user)
        preference.homepage_widgets = ["recent_transactions"]
        preference.recent_transaction_count = 3
        preference.save()

        self.assertEqual(
            len(self.widget("recent_transactions")["data"]["transactions"]), 3
        )


class WidgetSelectionTests(HomepageTestCase):
    def test_only_chosen_widgets_are_built_in_the_chosen_order(self):
        preference = UserPreference.for_user(self.user)
        preference.homepage_widgets = ["net_worth", "balances"]
        preference.save()

        slugs = [w["slug"] for w in build_homepage(self.user)["widgets"]]

        self.assertEqual(slugs, ["net_worth", "balances"])

    def test_an_unknown_widget_slug_does_not_break_the_page(self):
        preference = UserPreference.for_user(self.user)
        preference.homepage_widgets = ["balances", "a_widget_that_was_removed"]
        preference.save()

        slugs = [w["slug"] for w in build_homepage(self.user)["widgets"]]

        self.assertEqual(slugs, ["balances"])

    def test_each_person_gets_their_own_homepage(self):
        maddie = make_user("maddie")

        david_preference = UserPreference.for_user(self.user)
        david_preference.homepage_widgets = ["balances"]
        david_preference.save()

        maddie_preference = UserPreference.for_user(maddie)
        maddie_preference.homepage_widgets = ["net_worth"]
        maddie_preference.save()

        self.assertEqual([w["slug"] for w in build_homepage(self.user)["widgets"]], ["balances"])
        self.assertEqual([w["slug"] for w in build_homepage(maddie)["widgets"]], ["net_worth"])


class HomepageRenderTests(HomepageTestCase):
    def test_the_page_renders_with_the_default_widgets(self):
        self.sign_in()

        response = self.client.get(reverse("finance:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Checking")

    def test_a_brand_new_user_gets_a_working_page(self):
        # No UserPreference row exists yet; the page must not 500.
        maddie = make_user("maddie", with_device=True)
        self.client.force_login(maddie)
        session = self.client.session
        session["otp_device_id"] = TOTPDevice.objects.get(user=maddie).persistent_id
        session.save()

        response = self.client.get(reverse("finance:home"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(UserPreference.objects.filter(user=maddie).exists())


class TransactionOrderingAcrossWidgetsTests(HomepageTestCase):
    """Every widget that lists transactions by date shows newest first.

    None of them set an ordering: they inherit Transaction.Meta.ordering, so
    this is really a test that the model default is what the UI wants. If
    someone changes that default, this is what says which screens it moved.
    """

    def setUp(self):
        super().setUp()

        for day in (10, 1, 20, 5):
            make_transaction(
                self.checking,
                category=self.groceries,
                description_raw=f"DAY {day:02d}",
                posted_on=date(2026, 4, day),
                needs_review=True,
            )

    def test_the_recent_transactions_widget_is_newest_first(self):
        from finance.services.widgets import recent_transactions_widget

        widget = recent_transactions_widget(UserPreference.for_user(self.user))
        dates = [txn.posted_on for txn in widget["transactions"]]

        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_the_review_queue_widget_is_newest_first(self):
        from finance.services.widgets import review_queue_widget

        widget = review_queue_widget(UserPreference.for_user(self.user))
        dates = [txn.posted_on for txn in widget["transactions"]]

        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_the_model_default_is_newest_first(self):
        from finance.models import Transaction

        self.assertEqual(Transaction._meta.ordering, ["-posted_on", "-id"])
