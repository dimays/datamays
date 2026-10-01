"""The morning digest and the scheduler entry points."""

from datetime import date, datetime, timedelta
from unittest.mock import call, patch
from zoneinfo import ZoneInfo

from django.contrib.auth.models import Group
from django.core import mail
from django.core.management import call_command
from django.db import transaction as db_transaction
from django.test import TestCase, TransactionTestCase, override_settings

from household.access import HOUSEHOLD_GROUP
from household.models import HouseholdPreference, Milestone, Project, ProjectStatus
from household.services import digest

from .factories import make_chore, make_member

UTC = ZoneInfo("UTC")


def utc(*args):
    return datetime(*args, tzinfo=UTC)


# 12:30 UTC is 7:30am in Chicago during daylight time (CDT, UTC-5).
MORNING = utc(2026, 9, 30, 12, 30)
TODAY = date(2026, 9, 30)


def subscribe(user):
    preference = HouseholdPreference.for_user(user)
    preference.morning_digest = True
    preference.save()
    return preference


class ContentTests(TestCase):
    def setUp(self):
        self.david = make_member("david", first_name="David", email="david@example.com")

    def test_the_sections_in_order(self):
        make_chore(self.david, title="Call the plumber", starts_on=TODAY - timedelta(days=3), today=TODAY)
        make_chore(self.david, title="Unload the dishwasher", starts_on=TODAY, today=TODAY)
        make_chore(None, title="Clean the gutters", starts_on=TODAY + timedelta(days=4), today=TODAY)
        project = Project.objects.create(name="Kitchen", status=ProjectStatus.ACTIVE)
        Milestone.objects.create(project=project, name="Order hardware", target_on=TODAY - timedelta(days=2))
        Milestone.objects.create(project=project, name="Paint", target_on=TODAY + timedelta(days=10))
        Milestone.objects.create(project=project, name="Too far off", target_on=TODAY + timedelta(days=40))

        sections = digest.build_digest(self.david, TODAY)

        self.assertEqual([title for title, _ in sections],
                         ["Overdue", "Today", "Coming up this week", "Project milestones"])
        text = digest.render_digest(self.david, TODAY, sections)
        self.assertIn("Call the plumber — 3 days overdue", text)
        self.assertIn("Clean the gutters (either of us)", text)
        self.assertIn("Kitchen: Order hardware — late", text)
        self.assertIn("Kitchen: Paint — Sat Oct 10", text)
        self.assertNotIn("Too far off", text)

    @override_settings(REDIRECT_DOMAIN="https://www.datamays.com/")
    def test_links_point_at_the_site(self):
        text = digest.render_digest(self.david, TODAY, [("Today", ["  - x"])])

        self.assertIn("https://www.datamays.com/household/", text)
        self.assertIn("https://www.datamays.com/household/preferences/", text)

    def test_nothing_to_say_is_an_empty_digest(self):
        self.assertEqual(digest.build_digest(self.david, TODAY), [])


class SendingTests(TestCase):
    def setUp(self):
        self.david = make_member("david", first_name="David", email="david@example.com")
        make_chore(self.david, title="Unload the dishwasher", starts_on=TODAY, today=TODAY)

    def test_only_those_who_asked_get_one(self):
        make_member("maddie", email="maddie@example.com")
        subscribe(self.david)

        self.assertEqual(digest.send_due_digests(MORNING), 1)
        self.assertEqual(mail.outbox[0].to, ["david@example.com"])
        self.assertIn("1 today", mail.outbox[0].subject)

    def test_once_a_morning(self):
        subscribe(self.david)

        digest.send_due_digests(MORNING)
        digest.send_due_digests(MORNING + timedelta(hours=1))
        digest.send_due_digests(MORNING + timedelta(hours=8))

        self.assertEqual(len(mail.outbox), 1)

    def test_not_before_seven_household_time(self):
        subscribe(self.david)

        # 11:30 UTC is 6:30am in Chicago.
        digest.send_due_digests(utc(2026, 9, 30, 11, 30))

        self.assertEqual(mail.outbox, [])

    def test_an_empty_morning_sends_nothing_and_is_not_retried(self):
        quiet = make_member("quiet", email="quiet@example.com")
        preference = subscribe(quiet)

        digest.send_due_digests(MORNING)
        preference.refresh_from_db()

        self.assertEqual(mail.outbox, [])
        self.assertEqual(preference.last_digest_on, TODAY)

    def test_a_failed_send_is_retried_the_next_hour(self):
        preference = subscribe(self.david)

        with patch("household.services.digest.send_mail", side_effect=OSError("smtp down")):
            digest.send_due_digests(MORNING)
        preference.refresh_from_db()
        self.assertIsNone(preference.last_digest_on)

        digest.send_due_digests(MORNING + timedelta(hours=1))
        self.assertEqual(len(mail.outbox), 1)

    def test_someone_no_longer_in_the_household_gets_nothing(self):
        """Found in review: the digest ignored membership, and a removed
        member couldn't reach the preference to turn it off."""
        subscribe(self.david)
        self.david.groups.clear()
        self.assertEqual(digest.send_due_digests(MORNING), 0)

        self.david.groups.add(Group.objects.get(name=HOUSEHOLD_GROUP))
        self.david.is_active = False
        self.david.save()
        self.assertEqual(digest.send_due_digests(MORNING), 0)
        self.assertEqual(mail.outbox, [])

    def test_no_address_no_digest(self):
        self.david.email = ""
        self.david.save()
        subscribe(self.david)

        self.assertEqual(digest.send_due_digests(MORNING), 0)


class DaylightSavingTests(TestCase):
    """US clocks go back at 2am on Sunday, November 1, 2026."""

    def setUp(self):
        self.david = make_member("david", email="david@example.com")
        subscribe(self.david)

    def sent_at(self, moment):
        before = len(mail.outbox)
        # A chore due that day, so there is something to send.
        make_chore(self.david, title=f"Chore {moment}", starts_on=moment.astimezone(ZoneInfo("America/Chicago")).date())
        digest.send_due_digests(moment)
        return len(mail.outbox) > before

    def test_seven_am_local_on_both_sides_of_the_change(self):
        # Saturday: CDT, UTC-5. 12:30 UTC is 7:30am.
        self.assertTrue(self.sent_at(utc(2026, 10, 31, 12, 30)))
        # Sunday: CST, UTC-6. 12:30 UTC is now only 6:30am — not yet.
        self.assertFalse(self.sent_at(utc(2026, 11, 1, 12, 30)))
        # 13:30 UTC is 7:30am CST.
        self.assertTrue(self.sent_at(utc(2026, 11, 1, 13, 30)))


class IsolationTests(TransactionTestCase):
    """TransactionTestCase, not TestCase: the latter wraps each test in a
    transaction, which would make every send look like it ran inside one."""

    def test_mail_goes_out_with_no_transaction_open(self):
        david = make_member("david", email="david@example.com")
        make_chore(david, title="Unload the dishwasher", starts_on=TODAY, today=TODAY)
        subscribe(david)
        observed = {}

        def record(*args, **kwargs):
            observed["in_atomic_block"] = db_transaction.get_connection().in_atomic_block

        with patch("household.services.digest.send_mail", side_effect=record):
            digest.send_due_digests(MORNING)

        self.assertIn("in_atomic_block", observed)
        self.assertFalse(observed["in_atomic_block"])


class ChainTests(TestCase):
    def test_hourly_runs_household_steps_before_the_bank_sync(self):
        """A slow sync mustn't delay the morning email."""
        with patch("household.management.commands._chain.call_command") as run:
            call_command("household_hourly", verbosity=0)

        self.assertEqual(
            [c.args[0] for c in run.call_args_list],
            ["sweep_chores", "send_digests", "finance_hourly"],
        )

    def test_a_failing_step_does_not_stop_the_rest_but_fails_the_run(self):
        def run(name, **kwargs):
            if name == "sweep_chores":
                raise SystemExit(1)

        with patch("household.management.commands._chain.call_command", side_effect=run) as mocked:
            with self.assertRaises(SystemExit) as caught:
                call_command("household_hourly", verbosity=0)

        self.assertEqual(caught.exception.code, 1)
        self.assertIn(call("send_digests", verbosity=0), mocked.call_args_list)

    def test_daily_wraps_finance_daily(self):
        with patch("household.management.commands._chain.call_command") as run:
            call_command("household_daily", verbosity=0)

        self.assertEqual([c.args[0] for c in run.call_args_list], ["finance_daily", "sweep_chores"])


class ClaimTests(TestCase):
    """Round-1 review: overlapping hourly runs could both send."""

    def setUp(self):
        self.david = make_member("david", email="david@example.com")
        make_chore(self.david, title="Unload the dishwasher", starts_on=TODAY, today=TODAY)
        self.preference = subscribe(self.david)

    def test_a_second_run_holding_a_stale_copy_sends_nothing(self):
        stale = HouseholdPreference.objects.get(pk=self.preference.pk)

        self.assertTrue(digest.send_digest(self.preference, MORNING))
        self.assertFalse(digest.send_digest(stale, MORNING))
        self.assertEqual(len(mail.outbox), 1)

    def test_a_failed_build_releases_the_claim(self):
        """Round 2: the claim was taken before building, outside the release,
        so one database hiccup cost that morning's digest."""
        with patch("household.services.digest.build_digest", side_effect=RuntimeError("db hiccup")):
            self.assertFalse(digest.send_digest(self.preference, MORNING))

        self.preference.refresh_from_db()
        self.assertIsNone(self.preference.last_digest_on)
        self.assertTrue(digest.send_digest(self.preference, MORNING))

    def test_a_failed_send_releases_the_claim(self):
        with patch("household.services.digest.send_mail", side_effect=OSError("smtp down")):
            self.assertFalse(digest.send_digest(self.preference, MORNING))

        self.preference.refresh_from_db()
        self.assertIsNone(self.preference.last_digest_on)
