"""A round of UI gaps closed after using the app for real: activity filters
that survive a second submit, a budget click-through from the Budgets tab
itself, homepage widget ordering a person actually controls, a way to manage
institutions and manual accounts, and a reference for what an import file
needs to look like.
"""

from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from finance.models import (
    Account,
    Budget,
    BudgetPeriod,
    Category,
    Institution,
    Provider,
    UserPreference,
)
from finance.services.rollups import backfill_budget
from finance.services.widgets import WIDGET_CHOICES

from .factories import make_account, make_institution
from .test_access import make_user


def login(client):
    user = make_user("david", with_device=True)
    client.force_login(user)
    session = client.session
    session["otp_device_id"] = TOTPDevice.objects.get(user=user).persistent_id
    session.save()
    return user


class BudgetListClickThroughTests(TestCase):
    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)
        login(self.client)

        self.budget = Budget.objects.create(name="Groceries", amount=Decimal("400"))
        self.budget.categories.set([Category.objects.get(slug="food-groceries")])
        backfill_budget(self.budget)

    def test_the_budgets_page_links_to_the_current_periods_transactions(self):
        response = self.client.get(reverse("finance:budgets"))

        period = self.budget.budget_periods.order_by("-period_start").first()
        expected = (
            f"{reverse('finance:transactions')}?budget={self.budget.pk}"
            f"&start={period.period_start:%Y-%m-%d}&end={period.period_end:%Y-%m-%d}"
        )
        self.assertContains(response, expected)


class ActivityFilterFormTests(TestCase):
    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)
        login(self.client)

        self.institution = make_institution()
        self.checking = make_account(self.institution, name="Checking")
        self.budget = Budget.objects.create(name="Groceries", amount=Decimal("400"))
        self.budget.categories.set([Category.objects.get(slug="food-groceries")])

    def test_the_form_offers_a_budget_and_date_range_alongside_account(self):
        response = self.client.get(reverse("finance:transactions"))

        self.assertContains(response, 'name="budget"')
        self.assertContains(response, 'name="start"')
        self.assertContains(response, 'name="end"')
        self.assertContains(response, self.budget.name)

    def test_resubmitting_with_every_field_blank_does_not_error(self):
        response = self.client.get(
            reverse("finance:transactions"),
            {"account": "", "category": "", "budget": "", "start": "", "end": "", "q": ""},
        )
        self.assertEqual(response.status_code, 200)


class InstitutionManagementTests(TestCase):
    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)
        login(self.client)

    def test_creating_an_institution_with_no_connection(self):
        response = self.client.post(
            reverse("finance:institution_create"),
            {
                "name": "Northwestern Mutual",
                "provider": Provider.MANUAL,
                "website": "",
                "notes": "",
                "is_active": "on",
            },
        )

        self.assertRedirects(response, reverse("finance:institutions"))
        institution = Institution.objects.get(name="Northwestern Mutual")
        self.assertEqual(institution.slug, "northwestern-mutual")
        self.assertEqual(institution.provider, Provider.MANUAL)

    def test_the_list_page_shows_institutions_with_no_accounts_yet(self):
        make_institution(name="One Wealth")

        response = self.client.get(reverse("finance:institutions"))

        self.assertContains(response, "One Wealth")


class ManualAccountCreationTests(TestCase):
    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)
        login(self.client)
        self.institution = make_institution(name="CrossCountry Mortgage")

    def test_creating_a_manual_account_with_no_connection(self):
        response = self.client.post(
            reverse("finance:account_create"),
            {
                "institution": self.institution.pk,
                "name": "Mortgage",
                "account_type": "mortgage",
                "mask": "",
                "current_balance": "-287400.00",
                "balance_as_of": "2026-07-01T00:00",
                "debt_reported_positive": "on",
                "include_in_net_worth": "on",
                "include_in_spending": "on",
                "notes": "",
            },
        )

        self.assertRedirects(response, reverse("finance:settings"))
        account = Account.objects.get(name="Mortgage")
        self.assertIsNone(account.connection)
        self.assertEqual(account.institution, self.institution)
        self.assertEqual(account.current_balance, Decimal("-287400.00"))

    def test_a_manual_account_does_not_require_a_starting_balance(self):
        response = self.client.post(
            reverse("finance:account_create"),
            {
                "institution": self.institution.pk,
                "name": "401(k)",
                "account_type": "retirement",
                "mask": "",
                "current_balance": "",
                "balance_as_of": "",
                "include_in_net_worth": "on",
                "include_in_spending": "on",
                "notes": "",
            },
        )

        self.assertRedirects(response, reverse("finance:settings"))
        self.assertTrue(Account.objects.filter(name="401(k)").exists())


class PreferencesWidgetOrderTests(TestCase):
    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)
        self.user = login(self.client)

    def post_preferences(self, **overrides):
        data = {
            "widgets_selected": ["balances", "budgets", "recent_transactions"],
            "widget_order": "recent_transactions,balances,budgets,net_worth,review_queue",
            "accounts_selected": [],
            "budgets_selected": [],
            "recent_transaction_count": 8,
        }
        data.update(overrides)
        return self.client.post(reverse("finance:preferences"), data)

    def test_saving_respects_the_dragged_order_not_the_declared_order(self):
        self.post_preferences()

        preference = UserPreference.for_user(self.user)
        # Declared order is balances, budgets, recent_transactions, ... —
        # confirming the saved order is the dragged one, not that default.
        self.assertEqual(
            preference.homepage_widgets,
            ["recent_transactions", "balances", "budgets"],
        )

    def test_unchecking_a_widget_drops_it_without_disturbing_the_rest(self):
        self.post_preferences(widgets_selected=["balances", "recent_transactions"])

        preference = UserPreference.for_user(self.user)
        self.assertEqual(preference.homepage_widgets, ["recent_transactions", "balances"])

    def test_a_missing_order_field_falls_back_to_the_declared_order(self):
        self.post_preferences(widget_order="")

        preference = UserPreference.for_user(self.user)
        declared = [slug for slug, _ in WIDGET_CHOICES]
        expected = [slug for slug in declared if slug in {"balances", "budgets", "recent_transactions"}]
        self.assertEqual(preference.homepage_widgets, expected)

    def test_the_form_renders_every_widget_row_once(self):
        response = self.client.get(reverse("finance:preferences"))

        for slug, _ in WIDGET_CHOICES:
            self.assertContains(response, f'data-widget-row="{slug}"')


class ImportSchemaReferenceTests(TestCase):
    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)
        login(self.client)

    def test_the_page_lists_required_and_optional_fields_per_record_type(self):
        response = self.client.get(reverse("finance:import_schemas"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Transactions")
        self.assertContains(response, "Balances")
        self.assertContains(response, "Paychecks")
        self.assertContains(response, "Transaction date")
        self.assertContains(response, "One row per pay period")

    def test_it_is_linked_from_the_imports_list(self):
        response = self.client.get(reverse("finance:imports"))
        self.assertContains(response, reverse("finance:import_schemas"))
