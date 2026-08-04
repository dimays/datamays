"""The "hasn't synced" alert type.

One signal — the account's most recent balance snapshot, or the connection's
last_synced_at when there is one — has to serve both an automated connector
going quiet and a manual account nobody has refreshed. These tests check both
paths separately, and that the two produce differently-worded messages so a
person knows whether to check Settings or go find a statement.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from finance.models import (
    Account,
    AccountBalanceSnapshot,
    AccountConnection,
    Alert,
    AlertKind,
    Comparison,
    ThresholdUnit,
)
from finance.services.alerts import evaluate_alerts, last_activity_at, staleness_value

from .factories import make_account, make_institution
from .test_access import make_user


class LastActivityTests(TestCase):
    def setUp(self):
        self.institution = make_institution()

    def test_a_connected_account_uses_the_connections_own_timestamp(self):
        synced_at = timezone.now() - timedelta(hours=5)
        connection = AccountConnection.objects.create(
            institution=self.institution, label="Byline", access_secret="x",
            last_synced_at=synced_at,
        )
        account = make_account(self.institution, name="Checking", connection=connection)

        self.assertEqual(last_activity_at(account), synced_at)

    def test_a_manual_account_falls_back_to_its_newest_snapshot(self):
        account = make_account(self.institution, name="Policy")
        old = timezone.localdate() - timedelta(days=90)
        new = timezone.localdate() - timedelta(days=3)

        AccountBalanceSnapshot.objects.create(account=account, as_of=old, current=Decimal("100"))
        AccountBalanceSnapshot.objects.create(account=account, as_of=new, current=Decimal("110"))

        activity = last_activity_at(account)

        self.assertEqual(activity.date(), new)

    def test_an_account_with_nothing_at_all_returns_none(self):
        account = make_account(self.institution, name="Brand new")

        self.assertIsNone(last_activity_at(account))

    def test_a_connected_account_with_no_sync_yet_falls_back_to_a_snapshot(self):
        connection = AccountConnection.objects.create(
            institution=self.institution, label="Byline", access_secret="x"
        )
        account = make_account(self.institution, name="Checking", connection=connection)
        as_of = timezone.localdate() - timedelta(days=1)
        AccountBalanceSnapshot.objects.create(account=account, as_of=as_of, current=Decimal("1"))

        activity = last_activity_at(account)

        self.assertEqual(activity.date(), as_of)


class StalenessValueTests(TestCase):
    def setUp(self):
        self.institution = make_institution()
        self.user = make_user("david")

    def make_alert(self, account, unit, threshold="1"):
        return Alert(
            user=self.user, name="Stale", kind=AlertKind.SOURCE_STALE,
            account=account, comparison=Comparison.ABOVE,
            threshold=Decimal(threshold), threshold_unit=unit,
        )

    def test_value_is_expressed_in_the_alerts_own_unit(self):
        connection = AccountConnection.objects.create(
            institution=self.institution, label="Byline", access_secret="x",
            last_synced_at=timezone.now() - timedelta(hours=48),
        )
        account = make_account(self.institution, name="Checking", connection=connection)

        hours_alert = self.make_alert(account, ThresholdUnit.HOURS)
        days_alert = self.make_alert(account, ThresholdUnit.DAYS)

        self.assertAlmostEqual(float(staleness_value(hours_alert)), 48, delta=0.1)
        self.assertAlmostEqual(float(staleness_value(days_alert)), 2, delta=0.05)

    def test_no_baseline_yields_no_value_rather_than_a_false_positive(self):
        account = make_account(self.institution, name="Brand new")
        alert = self.make_alert(account, ThresholdUnit.DAYS)

        self.assertIsNone(staleness_value(alert))


class StalenessAlertEvaluationTests(TestCase):
    def setUp(self):
        self.institution = make_institution()
        self.user = make_user("david")
        self.user.email = "david@example.com"
        self.user.save()

    def test_a_quiet_connector_fires(self):
        connection = AccountConnection.objects.create(
            institution=self.institution, label="Nelnet", access_secret="x",
            last_synced_at=timezone.now() - timedelta(days=10),
        )
        account = make_account(self.institution, name="Student Loans", connection=connection)

        Alert.objects.create(
            user=self.user, name="Nelnet stale", kind=AlertKind.SOURCE_STALE,
            account=account, comparison=Comparison.ABOVE,
            threshold=Decimal("3"), threshold_unit=ThresholdUnit.DAYS,
        )

        fired = evaluate_alerts()

        self.assertEqual(len(fired), 1)
        self.assertIn("hasn't synced", fired[0].message)
        self.assertIn("Check the connection", fired[0].message)

    def test_a_recently_synced_connector_stays_quiet(self):
        connection = AccountConnection.objects.create(
            institution=self.institution, label="Byline", access_secret="x",
            last_synced_at=timezone.now() - timedelta(hours=2),
        )
        account = make_account(self.institution, name="Checking", connection=connection)

        Alert.objects.create(
            user=self.user, name="Byline stale", kind=AlertKind.SOURCE_STALE,
            account=account, comparison=Comparison.ABOVE,
            threshold=Decimal("3"), threshold_unit=ThresholdUnit.DAYS,
        )

        self.assertEqual(evaluate_alerts(), [])

    def test_a_stale_manual_account_fires_with_import_guidance(self):
        account = make_account(self.institution, name="Whole Life Policy")
        AccountBalanceSnapshot.objects.create(
            account=account,
            as_of=timezone.localdate() - timedelta(days=200),
            current=Decimal("18000"),
        )

        Alert.objects.create(
            user=self.user, name="Policy stale", kind=AlertKind.SOURCE_STALE,
            account=account, comparison=Comparison.ABOVE,
            threshold=Decimal("6"), threshold_unit=ThresholdUnit.MONTHS,
        )

        fired = evaluate_alerts()

        self.assertEqual(len(fired), 1)
        # Different guidance for a manual account: there is no connection to
        # check, only a statement to go find.
        self.assertIn("Import a fresh statement", fired[0].message)
        self.assertNotIn("Check the connection", fired[0].message)

    def test_a_brand_new_account_does_not_fire(self):
        account = make_account(self.institution, name="Just connected")

        Alert.objects.create(
            user=self.user, name="Too soon", kind=AlertKind.SOURCE_STALE,
            account=account, comparison=Comparison.ABOVE,
            threshold=Decimal("1"), threshold_unit=ThresholdUnit.HOURS,
        )

        self.assertEqual(evaluate_alerts(), [])

    def test_the_cooldown_still_applies(self):
        connection = AccountConnection.objects.create(
            institution=self.institution, label="Nelnet", access_secret="x",
            last_synced_at=timezone.now() - timedelta(days=10),
        )
        account = make_account(self.institution, name="Student Loans", connection=connection)

        Alert.objects.create(
            user=self.user, name="Stale", kind=AlertKind.SOURCE_STALE,
            account=account, comparison=Comparison.ABOVE,
            threshold=Decimal("3"), threshold_unit=ThresholdUnit.DAYS,
            cooldown_hours=24,
        )

        evaluate_alerts()
        second = evaluate_alerts()

        self.assertEqual(second, [])


class StalenessValidationTests(TestCase):
    def setUp(self):
        self.institution = make_institution()
        self.user = make_user("david")

    def test_an_account_is_required(self):
        alert = Alert(
            user=self.user, name="No account", kind=AlertKind.SOURCE_STALE,
            threshold=Decimal("3"), threshold_unit=ThresholdUnit.DAYS,
        )

        with self.assertRaises(ValidationError):
            alert.full_clean()

    def test_a_unit_is_required(self):
        account = make_account(self.institution, name="Checking")
        alert = Alert(
            user=self.user, name="No unit", kind=AlertKind.SOURCE_STALE,
            account=account, threshold=Decimal("3"),
        )

        with self.assertRaises(ValidationError):
            alert.full_clean()

    def test_comparison_is_forced_to_above_regardless_of_input(self):
        account = make_account(self.institution, name="Checking")
        alert = Alert(
            user=self.user, name="Wrong direction", kind=AlertKind.SOURCE_STALE,
            account=account, threshold=Decimal("3"), threshold_unit=ThresholdUnit.DAYS,
            comparison=Comparison.BELOW,
        )

        alert.full_clean()

        self.assertEqual(alert.comparison, Comparison.ABOVE)
