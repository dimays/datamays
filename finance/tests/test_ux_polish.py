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
    Owner,
    Provider,
    UserPreference,
)
from finance.services.rollups import backfill_budget
from finance.services.widgets import WIDGET_CHOICES

from .factories import make_account, make_institution, make_transaction
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


class ReviewQueueSaveButtonTests(TestCase):
    """The Save button on each Activity row shouldn't invite a pointless
    click when nothing has changed."""

    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)
        login(self.client)

        self.institution = make_institution()
        self.checking = make_account(self.institution, name="Checking")
        self.groceries = Category.objects.get(slug="food-groceries")

    def test_the_button_starts_disabled_for_an_already_categorized_row(self):
        make_transaction(
            self.checking,
            description_raw="MARIANOS",
            category=self.groceries,
            needs_review=False,
        )

        response = self.client.get(reverse("finance:transactions"))
        body = response.content.decode()

        # Alpine's initial state mirrors the saved category, so the disabled
        # expression evaluates true (nothing changed) until the person
        # actually picks something else.
        self.assertIn(
            f"initial: '{self.groceries.pk}', selected: '{self.groceries.pk}', needsReview: false",
            body,
        )
        self.assertIn(':disabled="selected === initial && !needsReview"', body)

    def test_picking_a_different_category_is_the_only_way_to_enable_it(self):
        # No "always"/create-a-rule shortcut folded into this save anymore —
        # rules are created from Settings > Category rules instead, where the
        # full pattern-matching system is actually visible.
        make_transaction(
            self.checking,
            description_raw="MARIANOS",
            category=self.groceries,
            needs_review=True,
        )

        response = self.client.get(reverse("finance:transactions"))

        self.assertNotContains(response, 'name="create_rule"')
        self.assertNotContains(response, ">always<")

    def test_an_archived_category_appears_in_its_own_optgroup(self):
        restaurants = Category.objects.get(slug="food-restaurants")
        restaurants.is_active = False
        restaurants.save(update_fields=["is_active"])

        make_transaction(self.checking, description_raw="MARIANOS", category=self.groceries)

        response = self.client.get(reverse("finance:transactions"))
        body = response.content.decode()

        self.assertIn('<optgroup label="Archived"', body)
        self.assertIn(f'value="{restaurants.pk}"', body)

    def test_an_active_category_never_appears_in_the_archived_optgroup(self):
        response = self.client.get(reverse("finance:transactions"))
        body = response.content.decode()

        self.assertNotIn('<optgroup label="Archived"', body)

    def test_a_row_needing_review_can_be_saved_without_changing_the_category(self):
        # The classifier's suggestion prefills the select, so a row that
        # merely needs confirming starts with selected === initial — the
        # Save button must still be enabled so "approve as suggested" is
        # possible without picking a different category first.
        make_transaction(
            self.checking,
            description_raw="MARIANOS",
            category=self.groceries,
            needs_review=True,
        )

        response = self.client.get(reverse("finance:transactions"))
        body = response.content.decode()

        self.assertIn(
            f"initial: '{self.groceries.pk}', selected: '{self.groceries.pk}', needsReview: true",
            body,
        )


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
                "owner": "joint",
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
                "owner": "joint",
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
                "owner": "david",
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


class OwnerFieldTests(TestCase):
    """Institutions and accounts can be tagged whose they are — bookkeeping
    only, never access control, since both of you can see and edit
    everything regardless of the value."""

    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)
        login(self.client)

    def test_an_institution_defaults_to_joint_when_not_specified_elsewhere(self):
        institution = make_institution(name="Byline")
        self.assertEqual(institution.owner, Owner.JOINT)

    def test_setting_an_institutions_owner_to_an_individual(self):
        institution = make_institution(name="Fidelity")

        response = self.client.post(
            reverse("finance:institution_edit", args=[institution.pk]),
            {
                "name": "Fidelity",
                "provider": Provider.MANUAL,
                "owner": "maddie",
                "website": "",
                "notes": "",
                "is_active": "on",
            },
        )

        self.assertRedirects(response, reverse("finance:institutions"))
        institution.refresh_from_db()
        self.assertEqual(institution.owner, Owner.MADDIE)

    def test_the_institutions_list_shows_the_owner(self):
        make_institution(name="David's Brokerage", owner=Owner.DAVID)

        response = self.client.get(reverse("finance:institutions"))
        self.assertContains(response, "David")

    def test_an_accounts_owner_is_editable(self):
        institution = make_institution()
        account = make_account(institution, name="Checking", owner=Owner.JOINT)

        response = self.client.post(
            reverse("finance:account_edit", args=[account.pk]),
            {
                "name": "Checking",
                "account_type": "checking",
                "owner": "maddie",
                "mask": "",
                "sort_order": 100,
                "notes": "",
                "is_active": "on",
                "include_in_net_worth": "on",
                "include_in_spending": "on",
                "debt_reported_positive": "on",
            },
        )

        self.assertRedirects(response, reverse("finance:settings"))
        account.refresh_from_db()
        self.assertEqual(account.owner, Owner.MADDIE)

    def test_the_settings_accounts_list_shows_the_owner(self):
        institution = make_institution()
        make_account(institution, name="Retirement 401k", owner=Owner.DAVID)

        response = self.client.get(reverse("finance:settings"))
        self.assertContains(response, "Retirement 401k")
        self.assertContains(response, "David")


class PreferenceDefaultsTests(TestCase):
    """The default lists must name slugs that actually exist.

    Chart sections derive from the registry so they cannot drift. Homepage
    widgets are a deliberate curated subset — a new widget should not switch
    itself on for everyone — so that list stays hand-written, and this is
    what stops a typo in it from silently showing nobody a widget.
    """

    def test_default_widgets_are_all_real(self):
        from finance.models.prefs import DEFAULT_HOMEPAGE_WIDGETS

        known = {slug for slug, _ in WIDGET_CHOICES}
        self.assertTrue(set(DEFAULT_HOMEPAGE_WIDGETS) <= known)

    def test_default_widgets_are_a_subset_not_everything(self):
        from finance.models.prefs import DEFAULT_HOMEPAGE_WIDGETS

        known = {slug for slug, _ in WIDGET_CHOICES}
        self.assertLess(set(DEFAULT_HOMEPAGE_WIDGETS), known)

    def test_default_chart_sections_track_the_registry(self):
        from finance.chart_sections import CHART_SECTIONS
        from finance.models.prefs import DEFAULT_CHART_SECTIONS

        self.assertEqual(
            DEFAULT_CHART_SECTIONS, [section.slug for section in CHART_SECTIONS]
        )
