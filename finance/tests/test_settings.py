"""Settings and preferences.

Settings are shared by the household; preferences are personal. The tests that
matter most here check that the boundary holds and that the stored credential
never reaches a page.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from finance.models import (
    Account,
    AccountBalanceSnapshot,
    AccountConnection,
    AccountType,
    BalanceSource,
    Budget,
    Category,
    CategoryRule,
    ConnectionStatus,
    UserPreference,
)
from finance.providers.base import ProviderError

from .factories import make_account, make_institution, make_transaction
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


class CategorizeNowTests(SettingsTestCase):
    """The button that runs the same pipeline the hourly job does, on
    demand, instead of it being CLI/Heroku-Scheduler only."""

    @patch("finance.views_settings.categorise_transactions")
    def test_it_runs_the_pipeline_and_reports_a_summary(self, run):
        from finance.services.categorize import CategorisationSummary

        run.return_value = CategorisationSummary(
            transfers=1, by_rule=2, by_memo=3, by_classifier=4, needs_review=5, unmatched=0
        )

        response = self.client.post(
            reverse("finance:settings"), {"action": "categorize"}, follow=True
        )

        run.assert_called_once()
        self.assertContains(response, "by rule: 2")
        self.assertContains(response, "needs review: 5")

    def test_the_uncategorized_count_reflects_the_pipelines_own_default(self):
        make_transaction(self.account, category=None, is_transfer=False)

        response = self.client.get(reverse("finance:settings"))

        self.assertContains(response, "1 transaction waiting right now")

    def test_categorize_now_is_gated_like_everything_else(self):
        self.client.logout()

        response = self.client.post(reverse("finance:settings"), {"action": "categorize"})

        self.assertEqual(response.status_code, 403)


class AccountCardRenderTests(SettingsTestCase):
    def test_an_account_with_a_balance_shows_when_it_was_last_updated(self):
        from django.utils import timezone

        self.account.balance_as_of = timezone.now()
        self.account.save()

        response = self.client.get(reverse("finance:settings"))

        self.assertContains(response, "Last updated on")

    def test_an_account_never_updated_says_so_rather_than_a_blank(self):
        self.account.balance_as_of = None
        self.account.save()

        response = self.client.get(reverse("finance:settings"))

        self.assertContains(response, "Never updated")


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

    def account_edit_payload(self, account, **overrides):
        payload = {
            "name": account.name,
            "account_type": account.account_type,
            "owner": "joint",
            "sort_order": 100,
            "notes": "",
            "is_active": "on",
            "include_in_net_worth": "on",
            "include_in_spending": "on",
        }
        payload.update(overrides)
        return payload

    def test_toggling_the_sign_convention_flips_the_stored_balance_immediately(self):
        card = make_account(
            self.institution,
            name="Capital One",
            connection=self.connection,
            account_type=AccountType.CREDIT_CARD,
            current_balance=Decimal("500.00"),
            debt_reported_positive=True,
        )

        # debt_reported_positive omitted -- an unchecked checkbox submits
        # nothing, which is how a real browser reports "turned it off."
        self.client.post(
            reverse("finance:account_edit", args=[card.pk]),
            self.account_edit_payload(card),
        )

        card.refresh_from_db()
        self.assertFalse(card.debt_reported_positive)
        self.assertEqual(card.current_balance, Decimal("-500.00"))

    def test_toggling_it_back_on_flips_the_balance_back(self):
        card = make_account(
            self.institution,
            name="Capital One",
            connection=self.connection,
            account_type=AccountType.CREDIT_CARD,
            current_balance=Decimal("-500.00"),
            debt_reported_positive=False,
        )

        self.client.post(
            reverse("finance:account_edit", args=[card.pk]),
            self.account_edit_payload(card, debt_reported_positive="on"),
        )

        card.refresh_from_db()
        self.assertTrue(card.debt_reported_positive)
        self.assertEqual(card.current_balance, Decimal("500.00"))

    def test_leaving_the_toggle_unchanged_does_not_touch_the_balance(self):
        card = make_account(
            self.institution,
            name="Capital One",
            connection=self.connection,
            account_type=AccountType.CREDIT_CARD,
            current_balance=Decimal("500.00"),
            debt_reported_positive=True,
        )

        self.client.post(
            reverse("finance:account_edit", args=[card.pk]),
            self.account_edit_payload(
                card, name="Capital One Venture", debt_reported_positive="on"
            ),
        )

        card.refresh_from_db()
        self.assertEqual(card.name, "Capital One Venture")
        self.assertEqual(card.current_balance, Decimal("500.00"))

    def test_the_settings_page_actually_renders_the_minus_sign_for_a_debt(self):
        card = make_account(
            self.institution,
            name="Capital One",
            connection=self.connection,
            account_type=AccountType.CREDIT_CARD,
            current_balance=Decimal("-500.00"),
        )

        response = self.client.get(reverse("finance:settings"))

        self.assertContains(response, "-$500.00")
        # Not the old behaviour: the raw amount must not also appear
        # unsigned, which would mean the minus sign silently got dropped.
        self.assertNotContains(response, ">$500.00<")

    def test_the_toggle_on_an_asset_account_never_touches_the_balance(self):
        # Ignored for asset accounts by design (per the field's own
        # help_text) -- guards the flip logic against a stray submission.
        self.account.current_balance = Decimal("4200.00")
        self.account.debt_reported_positive = True
        self.account.save()

        self.client.post(
            reverse("finance:account_edit", args=[self.account.pk]),
            self.account_edit_payload(self.account),
        )

        self.account.refresh_from_db()
        self.assertFalse(self.account.debt_reported_positive)
        self.assertEqual(self.account.current_balance, Decimal("4200.00"))


class ManualBalanceUpdateTests(SettingsTestCase):
    """The lightweight alternative to a CSV balances import for one account."""

    def update_balance(self, account, **overrides):
        payload = {
            "action": "update_balance",
            "as_of": "2026-08-01",
            "current_balance": "5000.00",
            "available_balance": "",
        }
        payload.update(overrides)
        return self.client.post(reverse("finance:account_edit", args=[account.pk]), payload)

    def test_it_updates_the_account_fields(self):
        self.update_balance(self.account, current_balance="5123.45")

        self.account.refresh_from_db()
        self.assertEqual(self.account.current_balance, Decimal("5123.45"))
        self.assertIsNotNone(self.account.balance_as_of)

    def test_it_records_a_snapshot_sourced_as_manual(self):
        self.update_balance(self.account, current_balance="5123.45")

        snapshot = AccountBalanceSnapshot.objects.get(
            account=self.account, as_of=date(2026, 8, 1)
        )
        self.assertEqual(snapshot.current, Decimal("5123.45"))
        self.assertEqual(snapshot.source, BalanceSource.MANUAL)

    def test_it_works_on_a_connected_account_too(self):
        # The account this test case sets up already has a live connection —
        # per the explicit ask, manual entry is available for any account,
        # not only ones with no connection.
        self.assertIsNotNone(self.account.connection_id)

        response = self.update_balance(self.account, current_balance="6000.00")

        self.assertRedirects(response, reverse("finance:settings"))
        self.account.refresh_from_db()
        self.assertEqual(self.account.current_balance, Decimal("6000.00"))

    def test_available_balance_is_optional(self):
        self.update_balance(self.account, current_balance="100.00", available_balance="90.00")

        self.account.refresh_from_db()
        self.assertEqual(self.account.available_balance, Decimal("90.00"))

    def test_an_invalid_amount_is_rejected_without_touching_the_account(self):
        response = self.update_balance(self.account, current_balance="not-a-number")

        self.account.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.account.current_balance, Decimal("4200.00"))

    def test_re_running_for_the_same_date_overwrites_rather_than_stacks(self):
        self.update_balance(self.account, current_balance="100.00")
        self.update_balance(self.account, current_balance="200.00")

        self.assertEqual(
            AccountBalanceSnapshot.objects.filter(
                account=self.account, as_of=date(2026, 8, 1)
            ).count(),
            1,
        )
        snapshot = AccountBalanceSnapshot.objects.get(
            account=self.account, as_of=date(2026, 8, 1)
        )
        self.assertEqual(snapshot.current, Decimal("200.00"))

    def test_it_is_gated_like_everything_else(self):
        self.client.logout()

        response = self.update_balance(self.account)

        self.assertEqual(response.status_code, 403)


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

    def test_chart_section_selection_is_saved_in_declaration_order(self):
        self.client.post(
            reverse("finance:preferences"),
            {
                "widgets_selected": ["balances"],
                # Submitted out of order; stored order should be canonical.
                "chart_sections_selected": ["net_cash_flow", "spend_over_time"],
                "recent_transaction_count": 8,
            },
        )

        preference = UserPreference.for_user(self.user)
        self.assertEqual(
            preference.chart_sections, ["spend_over_time", "net_cash_flow"]
        )

    def test_a_new_preference_defaults_to_every_chart_section(self):
        response = self.client.get(reverse("finance:preferences"))

        self.assertEqual(
            response.context["form"].fields["chart_sections_selected"].initial,
            UserPreference.for_user(self.user).chart_section_order,
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
