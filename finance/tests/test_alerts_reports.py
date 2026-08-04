"""Alerts and scheduled reports.

Email is captured by Django's locmem backend; nothing leaves the test process.
"""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from finance.models import (
    Account,
    AccountConnection,
    AccountType,
    Alert,
    AlertEvent,
    AlertKind,
    Budget,
    BudgetPeriod,
    Category,
    Comparison,
    ReportCadence,
    ScheduledReport,
)
from finance.services.alerts import evaluate_alerts
from finance.services import alerts as alert_service
from finance.services import reports as report_service

from .factories import make_account, make_institution, make_transaction
from .test_access import make_user


class AlertTestCase(TestCase):
    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)

        self.user = make_user("david")
        self.user.email = "david@example.com"
        self.user.save()

        self.institution = make_institution()
        self.connection = AccountConnection.objects.create(
            institution=self.institution, label="Byline", access_secret="x"
        )
        self.checking = make_account(
            self.institution,
            name="Checking",
            connection=self.connection,
            current_balance=Decimal("250.00"),
            balance_as_of=timezone.now(),
        )
        self.card = make_account(
            self.institution,
            name="Card",
            account_type=AccountType.CREDIT_CARD,
            connection=self.connection,
            current_balance=Decimal("-2400.00"),
            balance_as_of=timezone.now(),
        )

        self.groceries = Category.objects.get(slug="food-groceries")

    def make_budget_period(self, actual="600.00", target="800.00", name="Groceries"):
        today = timezone.localdate()
        budget = Budget.objects.create(name=name, amount=Decimal(target))
        budget.categories.set([self.groceries])

        period = BudgetPeriod.objects.create(
            budget=budget,
            period_start=today.replace(day=1),
            period_end=today.replace(day=28),
            target_amount=Decimal(target),
            actual_amount=Decimal(actual),
        )

        return budget, period


class BalanceAlertTests(AlertTestCase):
    def make_alert(self, **kwargs):
        kwargs.setdefault("name", "Checking running low")
        kwargs.setdefault("kind", AlertKind.ACCOUNT_BALANCE)
        kwargs.setdefault("account", self.checking)
        kwargs.setdefault("comparison", Comparison.BELOW)
        kwargs.setdefault("threshold", Decimal("500.00"))

        return Alert.objects.create(user=self.user, **kwargs)

    def test_a_breached_threshold_fires_and_emails(self):
        self.make_alert()

        fired = evaluate_alerts()

        self.assertEqual(len(fired), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Checking", mail.outbox[0].body)
        self.assertTrue(fired[0].was_delivered)

    def test_an_unbreached_threshold_stays_quiet(self):
        self.make_alert(threshold=Decimal("100.00"))

        self.assertEqual(evaluate_alerts(), [])
        self.assertEqual(len(mail.outbox), 0)

    def test_a_card_balance_is_compared_as_an_amount_owed(self):
        # Stored negative for net worth; "above $2,000" should mean owing more.
        self.make_alert(
            name="Card too high",
            account=self.card,
            comparison=Comparison.ABOVE,
            threshold=Decimal("2000.00"),
        )

        fired = evaluate_alerts()

        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0].observed_value, Decimal("2400.00"))

    def test_the_cooldown_prevents_hourly_repeats(self):
        self.make_alert()

        evaluate_alerts()
        evaluate_alerts()
        evaluate_alerts()

        # Otherwise the hourly chain would email every hour until fixed, and
        # an alert people mute is worse than no alert.
        self.assertEqual(len(mail.outbox), 1)

    def test_it_fires_again_once_the_cooldown_expires(self):
        alert = self.make_alert(cooldown_hours=1)
        evaluate_alerts()

        alert.last_triggered_at = timezone.now() - timedelta(hours=2)
        alert.save()

        evaluate_alerts()

        self.assertEqual(len(mail.outbox), 2)

    def test_inactive_alerts_are_skipped(self):
        self.make_alert(is_active=False)

        self.assertEqual(evaluate_alerts(), [])

    def test_a_stale_balance_is_flagged_in_the_message(self):
        self.checking.balance_as_of = timezone.now() - timedelta(days=5)
        self.checking.save()
        self.make_alert()

        evaluate_alerts()

        self.assertIn("may be out of date", mail.outbox[0].body)

    def test_an_account_with_no_balance_does_not_fire(self):
        self.checking.current_balance = None
        self.checking.save()
        self.make_alert()

        self.assertEqual(evaluate_alerts(), [])

    def test_a_mail_failure_is_recorded_not_raised(self):
        self.make_alert()

        with patch("finance.services.alerts.send_mail", side_effect=OSError("smtp down")):
            fired = evaluate_alerts()

        # A mail outage must not stop the remaining alerts being evaluated.
        self.assertEqual(len(fired), 1)
        self.assertFalse(fired[0].was_delivered)
        self.assertIn("smtp down", fired[0].delivery_error)

    def test_a_user_without_an_email_address_is_recorded(self):
        self.user.email = ""
        self.user.save()
        self.make_alert()

        fired = evaluate_alerts()

        self.assertFalse(fired[0].was_delivered)
        self.assertIn("No email", fired[0].delivery_error)


class BudgetAlertTests(AlertTestCase):
    def test_a_percentage_alert_fires(self):
        budget, _ = self.make_budget_period(actual="700.00", target="800.00")

        Alert.objects.create(
            user=self.user,
            name="Groceries at 80%",
            kind=AlertKind.BUDGET_PERCENT,
            budget=budget,
            comparison=Comparison.ABOVE,
            threshold=Decimal("80"),
        )

        fired = evaluate_alerts()

        self.assertEqual(len(fired), 1)
        # 700 of 800 is 87.5%, which renders rounded.
        self.assertIn("88%", mail.outbox[0].body)

    def test_an_amount_alert_fires(self):
        budget, _ = self.make_budget_period(actual="750.00")

        Alert.objects.create(
            user=self.user,
            name="Groceries past $700",
            kind=AlertKind.BUDGET_AMOUNT,
            budget=budget,
            comparison=Comparison.ABOVE,
            threshold=Decimal("700.00"),
        )

        self.assertEqual(len(evaluate_alerts()), 1)

    def test_the_period_gate_suppresses_a_late_period_alert(self):
        budget, period = self.make_budget_period(actual="700.00")

        # "Tell me only if we pass 80% before we are 10% through the month."
        Alert.objects.create(
            user=self.user,
            name="Groceries too fast",
            kind=AlertKind.BUDGET_PERCENT,
            budget=budget,
            comparison=Comparison.ABOVE,
            threshold=Decimal("80"),
            only_after_period_fraction=0.0,
        )

        period.period_start = timezone.localdate() - timedelta(days=1)
        period.period_end = timezone.localdate() + timedelta(days=200)
        period.save()

        # Barely into a long period, so the gate at 0.0 still passes.
        self.assertEqual(len(evaluate_alerts()), 1)

    def test_the_period_gate_blocks_when_not_far_enough_through(self):
        budget, period = self.make_budget_period(actual="700.00")

        Alert.objects.create(
            user=self.user,
            name="Groceries too fast",
            kind=AlertKind.BUDGET_PERCENT,
            budget=budget,
            comparison=Comparison.ABOVE,
            threshold=Decimal("80"),
            only_after_period_fraction=0.9,
        )

        period.period_start = timezone.localdate()
        period.period_end = timezone.localdate() + timedelta(days=60)
        period.save()

        self.assertEqual(evaluate_alerts(), [])

    def test_a_budget_with_no_current_period_does_not_fire(self):
        budget = Budget.objects.create(name="Unrolled", amount=Decimal("500"))

        Alert.objects.create(
            user=self.user,
            name="Never",
            kind=AlertKind.BUDGET_PERCENT,
            budget=budget,
            comparison=Comparison.ABOVE,
            threshold=Decimal("50"),
        )

        self.assertEqual(evaluate_alerts(), [])

    def test_the_message_includes_pacing(self):
        budget, _ = self.make_budget_period(actual="700.00")

        Alert.objects.create(
            user=self.user,
            name="Groceries",
            kind=AlertKind.BUDGET_PERCENT,
            budget=budget,
            comparison=Comparison.ABOVE,
            threshold=Decimal("50"),
        )

        evaluate_alerts()

        self.assertIn("pace", mail.outbox[0].body)

    def test_dry_run_records_without_sending(self):
        budget, _ = self.make_budget_period(actual="700.00")
        Alert.objects.create(
            user=self.user,
            name="Groceries",
            kind=AlertKind.BUDGET_PERCENT,
            budget=budget,
            comparison=Comparison.ABOVE,
            threshold=Decimal("50"),
        )

        call_command("send_alerts", "--dry-run", verbosity=0)

        self.assertEqual(AlertEvent.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)


class ReportTests(AlertTestCase):
    def make_report(self, **kwargs):
        kwargs.setdefault("name", "Weekly summary")
        kwargs.setdefault("cadence", ReportCadence.WEEKLY)
        kwargs.setdefault("sections", ["balances", "budgets", "spend"])
        kwargs.setdefault("send_day", timezone.localdate().isoweekday())

        return ScheduledReport.objects.create(user=self.user, **kwargs)

    def test_a_due_report_is_sent(self):
        self.make_budget_period()
        report = self.make_report()

        sent = report_service.send_due_reports()

        self.assertEqual(len(sent), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("BALANCES", mail.outbox[0].body)
        self.assertIn("Groceries", mail.outbox[0].body)

        report.refresh_from_db()
        self.assertIsNotNone(report.last_sent_at)

    def test_a_report_due_another_day_is_not_sent(self):
        other_day = (timezone.localdate().isoweekday() % 7) + 1
        self.make_report(send_day=other_day)

        self.assertEqual(report_service.send_due_reports(), [])

    def test_a_report_is_not_sent_twice_in_one_day(self):
        self.make_report()

        report_service.send_due_reports()
        report_service.send_due_reports()

        self.assertEqual(len(mail.outbox), 1)

    def test_only_the_chosen_sections_appear(self):
        self.make_budget_period()
        self.make_report(sections=["budgets"])

        report_service.send_due_reports()

        body = mail.outbox[0].body
        self.assertIn("BUDGETS", body)
        self.assertNotIn("BALANCES", body)

    def test_the_review_section_reports_the_queue(self):
        transaction = make_transaction(self.checking, description_raw="MYSTERY")
        transaction.needs_review = True
        transaction.save()

        self.make_report(sections=["review"])
        report_service.send_due_reports()

        self.assertIn("1 transaction waiting", mail.outbox[0].body)

    def test_inactive_reports_are_skipped(self):
        self.make_report(is_active=False)

        self.assertEqual(report_service.send_due_reports(), [])

    def test_a_monthly_report_is_due_on_its_day_of_month(self):
        today = timezone.localdate()
        report = self.make_report(
            cadence=ReportCadence.MONTHLY, send_day=min(today.day, 28)
        )

        if today.day <= 28:
            self.assertTrue(report_service.is_due(report, today))

    def test_a_send_failure_leaves_last_sent_alone_so_it_retries(self):
        report = self.make_report()

        with patch("finance.services.reports.send_mail", side_effect=OSError("smtp down")):
            self.assertEqual(report_service.send_due_reports(), [])

        report.refresh_from_db()
        self.assertIsNone(report.last_sent_at)


class ChainTests(AlertTestCase):
    def test_the_hourly_chain_runs_every_step_in_order(self):
        with patch("finance.management.commands.finance_hourly.call_command") as call:
            call_command("finance_hourly", verbosity=0)

        self.assertEqual(
            [c.args[0] for c in call.call_args_list],
            ["sync_accounts", "categorize_transactions", "rollup_budgets", "send_alerts"],
        )

    def test_the_daily_chain_runs_every_step_in_order(self):
        with patch("finance.management.commands.finance_daily.call_command") as call:
            call_command("finance_daily", verbosity=0)

        self.assertEqual(
            [c.args[0] for c in call.call_args_list],
            [
                "sync_accounts",
                "categorize_transactions",
                "snapshot_balances",
                "rollup_budgets",
                "send_reports",
            ],
        )

    def test_the_hourly_sync_is_limited_to_day_to_day_accounts(self):
        with patch("finance.management.commands.finance_hourly.call_command") as call:
            call_command("finance_hourly", verbosity=0)

        self.assertTrue(call.call_args_list[0].kwargs["high_frequency_only"])

    def test_the_daily_sync_covers_everything(self):
        with patch("finance.management.commands.finance_daily.call_command") as call:
            call_command("finance_daily", verbosity=0)

        self.assertNotIn("high_frequency_only", call.call_args_list[0].kwargs)

    def test_a_failing_step_does_not_stop_the_rest(self):
        def fail_on_sync(name, *args, **kwargs):
            if name == "sync_accounts":
                raise RuntimeError("provider down")

        with patch(
            "finance.management.commands.finance_hourly.call_command",
            side_effect=fail_on_sync,
        ) as call:
            with self.assertRaises(SystemExit):
                call_command("finance_hourly", verbosity=0)

        # Budgets still roll up from the data already present.
        self.assertEqual(len(call.call_args_list), 4)

    def test_a_failing_chain_exits_non_zero(self):
        with patch(
            "finance.management.commands.finance_daily.call_command",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(SystemExit) as caught:
                call_command("finance_daily", verbosity=0)

        # Non-zero so a broken scheduled run is visible in Heroku's logs.
        self.assertEqual(caught.exception.code, 1)


class AlertUIScopingTests(AlertTestCase):
    """Alerts are personal — one person must never see or edit the other's."""

    def setUp(self):
        super().setUp()

        from django_otp.plugins.otp_totp.models import TOTPDevice

        self.device = TOTPDevice.objects.create(user=self.user, name="d", confirmed=True)
        self.maddie = make_user("maddie")

        self.mine = Alert.objects.create(
            user=self.user,
            name="Mine",
            kind=AlertKind.ACCOUNT_BALANCE,
            account=self.checking,
            comparison=Comparison.BELOW,
            threshold=Decimal("500"),
        )
        self.theirs = Alert.objects.create(
            user=self.maddie,
            name="Theirs",
            kind=AlertKind.ACCOUNT_BALANCE,
            account=self.checking,
            comparison=Comparison.BELOW,
            threshold=Decimal("100"),
        )

        self.client.force_login(self.user)
        session = self.client.session
        session["otp_device_id"] = self.device.persistent_id
        session.save()

    def test_the_list_shows_only_my_alerts(self):
        from django.urls import reverse

        response = self.client.get(reverse("finance:alerts"))

        self.assertContains(response, "Mine")
        self.assertNotContains(response, "Theirs")

    def test_i_cannot_open_someone_elses_alert(self):
        from django.urls import reverse

        response = self.client.get(reverse("finance:alert_edit", args=[self.theirs.pk]))

        self.assertEqual(response.status_code, 404)

    def test_a_new_alert_is_filed_under_me(self):
        from django.urls import reverse

        self.client.post(
            reverse("finance:alert_create"),
            {
                "name": "New one",
                "kind": AlertKind.ACCOUNT_BALANCE,
                "account": self.checking.pk,
                "comparison": Comparison.BELOW,
                "threshold": "300",
                "cooldown_hours": 24,
                "is_active": "on",
            },
        )

        self.assertEqual(Alert.objects.get(name="New one").user, self.user)

    def test_each_person_is_alerted_at_their_own_threshold(self):
        # Checking is at $250, so both thresholds are breached differently.
        self.maddie.email = "maddie@example.com"
        self.maddie.save()

        fired = evaluate_alerts()

        self.assertEqual({event.alert.name for event in fired}, {"Mine"})
