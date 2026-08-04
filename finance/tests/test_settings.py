"""Settings and preferences.

Settings are shared by the household; preferences are personal. The tests that
matter most here check that the boundary holds and that the stored credential
never reaches a page.
"""

from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from finance.models import (
    Account,
    AccountConnection,
    AccountType,
    Budget,
    Category,
    CategoryRule,
    ConnectionStatus,
    UserPreference,
)
from finance.providers.base import ProviderError

from .factories import make_account, make_institution
from .test_access import make_user

ACCESS_URL = "https://user:super-secret-token@bridge.simplefin.org/simplefin"


class SettingsTestCase(TestCase):
    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)

        self.user = make_user("david", with_device=True)
        self.institution = make_institution()
        self.connection = AccountConnection.objects.create(
            institution=self.institution, label="Byline (joint)", access_secret=ACCESS_URL
        )
        self.account = make_account(
            self.institution,
            name="Checking",
            connection=self.connection,
            current_balance=Decimal("4200.00"),
        )

        self.sign_in(self.user)

    def sign_in(self, user):
        self.client.force_login(user)
        session = self.client.session
        session["otp_device_id"] = TOTPDevice.objects.get(user=user).persistent_id
        session.save()


class CredentialExposureTests(SettingsTestCase):
    """The stored access URL must never reach a rendered page."""

    def test_the_settings_page_does_not_leak_the_credential(self):
        response = self.client.get(reverse("finance:settings"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "super-secret-token")

    def test_the_connection_detail_page_does_not_leak_the_credential(self):
        response = self.client.get(
            reverse("finance:connection_detail", args=[self.connection.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "super-secret-token")
        self.assertNotContains(response, "bridge.simplefin.org/simplefin")


class ConnectionManagementTests(SettingsTestCase):
    @patch("finance.views_settings.sync_connection")
    @patch("finance.views_settings.claim_access_url")
    def test_connecting_exchanges_the_token_and_tests_it(self, claim, sync):
        claim.return_value = ACCESS_URL
        sync.return_value.status = "success"
        sync.return_value.accounts_synced = 3
        sync.return_value.transactions_created = 42

        response = self.client.post(
            reverse("finance:connection_create"),
            {
                "label": "Chase (personal)",
                "setup_token": "a-token",
            },
        )

        self.assertRedirects(response, reverse("finance:settings"))

        connection = AccountConnection.objects.get(label="Chase (personal)")
        self.assertEqual(connection.access_secret, ACCESS_URL)
        # No institution is chosen up front anymore -- a single token can
        # cover more than one, resolved per account during sync instead.
        self.assertIsNone(connection.institution)

        # Test-on-save: a connection that cannot pull is not really connected.
        sync.assert_called_once()

    @patch("finance.views_settings.claim_access_url")
    def test_a_rejected_token_reports_the_error_and_saves_nothing(self, claim):
        claim.side_effect = ProviderError("Tokens can only be claimed once.")

        response = self.client.post(
            reverse("finance:connection_create"),
            {"label": "Chase (personal)", "setup_token": "already-used"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "claimed once")
        self.assertFalse(AccountConnection.objects.filter(label="Chase (personal)").exists())

    @patch("finance.views_settings.sync_connection")
    def test_a_failing_first_sync_still_saves_the_connection_with_a_warning(self, sync):
        sync.return_value.status = "failed"
        sync.return_value.error_message = "could not reach institution"

        with patch("finance.views_settings.claim_access_url", return_value=ACCESS_URL):
            response = self.client.post(
                reverse("finance:connection_create"),
                {"label": "Nelnet", "setup_token": "token"},
                follow=True,
            )

        self.assertTrue(AccountConnection.objects.filter(label="Nelnet").exists())
        self.assertContains(response, "could not reach institution")

    def test_a_connection_can_be_disabled_and_re_enabled(self):
        url = reverse("finance:connection_detail", args=[self.connection.pk])

        self.client.post(url, {"action": "disable"})
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, ConnectionStatus.DISABLED)

        self.client.post(url, {"action": "enable"})
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, ConnectionStatus.ACTIVE)

    def test_erasing_the_credential_clears_it_and_disables_the_connection(self):
        self.client.post(
            reverse("finance:connection_detail", args=[self.connection.pk]),
            {"action": "forget"},
        )

        self.connection.refresh_from_db()
        self.assertEqual(self.connection.access_secret, "")
        self.assertEqual(self.connection.status, ConnectionStatus.DISABLED)
        self.assertFalse(self.connection.is_syncable)

    @patch("finance.views_settings.sync_connection")
    def test_sync_now_runs_a_manual_sync(self, sync):
        sync.return_value.status = "success"
        sync.return_value.accounts_synced = 1
        sync.return_value.transactions_created = 0
        sync.return_value.transactions_updated = 0

        self.client.post(
            reverse("finance:connection_detail", args=[self.connection.pk]),
            {"action": "sync"},
        )

        sync.assert_called_once()


class AccountSettingsTests(SettingsTestCase):
    def test_an_account_type_can_be_corrected(self):
        self.client.post(
            reverse("finance:account_edit", args=[self.account.pk]),
            {
                "name": "Joint Checking",
                "account_type": AccountType.MONEY_MARKET,
                "owner": "joint",
                "mask": "4471",
                "sort_order": 100,
                "notes": "",
                "is_active": "on",
                "include_in_net_worth": "on",
                "include_in_spending": "on",
                "debt_reported_positive": "on",
            },
        )

        self.account.refresh_from_db()
        self.assertEqual(self.account.account_type, AccountType.MONEY_MARKET)
        self.assertEqual(self.account.name, "Joint Checking")

    def test_the_sign_convention_toggle_is_editable(self):
        # The escape hatch for an institution that reports debts negative.
        self.client.post(
            reverse("finance:account_edit", args=[self.account.pk]),
            {
                "name": "Checking",
                "account_type": AccountType.CREDIT_CARD,
                "owner": "joint",
                "sort_order": 100,
                "notes": "",
                "is_active": "on",
            },
        )

        self.account.refresh_from_db()
        self.assertFalse(self.account.debt_reported_positive)


class RuleManagementTests(SettingsTestCase):
    def setUp(self):
        super().setUp()
        self.rule = CategoryRule.objects.create(
            pattern="marianos", category=Category.objects.get(slug="food-groceries")
        )

    def test_rules_are_listed(self):
        response = self.client.get(reverse("finance:rules"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "marianos")

    def test_a_rule_can_be_paused_without_deleting_it(self):
        self.client.post(reverse("finance:rules"), {"rule": self.rule.pk, "action": "toggle"})

        self.rule.refresh_from_db()
        self.assertFalse(self.rule.is_active)

    def test_a_rule_can_be_deleted(self):
        self.client.post(reverse("finance:rules"), {"rule": self.rule.pk, "action": "delete"})

        self.assertFalse(CategoryRule.objects.filter(pk=self.rule.pk).exists())


class PreferenceTests(SettingsTestCase):
    def test_widget_selection_is_saved_in_declaration_order(self):
        self.client.post(
            reverse("finance:preferences"),
            {
                # Submitted out of order; stored order should be canonical so
                # the homepage reads the same way every time.
                "widgets_selected": ["review_queue", "balances"],
                "recent_transaction_count": 8,
            },
        )

        preference = UserPreference.for_user(self.user)
        self.assertEqual(preference.homepage_widgets, ["balances", "review_queue"])

    def test_account_and_budget_filters_are_saved(self):
        budget = Budget.objects.create(name="Groceries", amount=Decimal("700"))

        self.client.post(
            reverse("finance:preferences"),
            {
                "widgets_selected": ["balances"],
                "accounts_selected": [self.account.pk],
                "budgets_selected": [budget.pk],
                "recent_transaction_count": 5,
            },
        )

        preference = UserPreference.for_user(self.user)
        self.assertEqual(preference.homepage_account_ids, [self.account.pk])
        self.assertEqual(preference.homepage_budget_ids, [budget.pk])
        self.assertEqual(preference.recent_transaction_count, 5)

    def test_preferences_persist_across_sessions(self):
        self.client.post(
            reverse("finance:preferences"),
            {"widgets_selected": ["net_worth"], "recent_transaction_count": 3},
        )

        self.client.logout()
        self.sign_in(self.user)

        self.assertEqual(
            UserPreference.for_user(self.user).homepage_widgets, ["net_worth"]
        )

        # And the form comes back pre-filled with it.
        response = self.client.get(reverse("finance:preferences"))
        self.assertEqual(
            response.context["form"].fields["widgets_selected"].initial, ["net_worth"]
        )

    def test_one_person_cannot_change_the_others_preferences(self):
        maddie = make_user("maddie", with_device=True)
        maddie_preference = UserPreference.for_user(maddie)
        maddie_preference.homepage_widgets = ["net_worth"]
        maddie_preference.save()

        self.client.post(
            reverse("finance:preferences"),
            {"widgets_selected": ["balances"], "recent_transaction_count": 8},
        )

        maddie_preference.refresh_from_db()
        self.assertEqual(maddie_preference.homepage_widgets, ["net_worth"])
        self.assertEqual(
            UserPreference.for_user(self.user).homepage_widgets, ["balances"]
        )


class SettingsAccessTests(SettingsTestCase):
    def test_settings_pages_are_gated(self):
        self.client.logout()

        urls = [
            reverse("finance:settings"),
            reverse("finance:connection_create"),
            reverse("finance:connection_detail", args=[self.connection.pk]),
            reverse("finance:account_edit", args=[self.account.pk]),
            reverse("finance:rules"),
            reverse("finance:preferences"),
        ]

        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
