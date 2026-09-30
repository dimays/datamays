"""The local demo household, and the guard that keeps it local.

The seed flushes and rewrites a database, and the repo's `.env` points at
production. The guard is the part of this worth testing hardest.
"""

from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django_otp.plugins.otp_totp.models import TOTPDevice

from finance.access import is_household_member
from finance.dates import household_today
from finance.models import Budget, BudgetPeriod, Transaction
from household.services import demo


def run(*args):
    out = StringIO()
    call_command(*args, stdout=out)
    return out.getvalue()


class GuardTests(TestCase):
    def test_every_entry_point_refuses_a_non_sqlite_database(self):
        with patch.object(demo.connection, "vendor", "postgresql"):
            with self.assertRaises(demo.NotALocalDatabase):
                demo.seed()

            for command in (["seed_household_demo"], ["seed_household_demo", "--reset"],
                            ["demo_totp_code", "david"]):
                with self.subTest(command=command):
                    with self.assertRaisesMessage(CommandError, "postgresql"):
                        run(*command)

    def test_the_refusal_happens_before_reset_wipes_anything(self):
        demo.seed()

        with patch.object(demo.connection, "vendor", "postgresql"):
            with self.assertRaises(CommandError):
                run("seed_household_demo", "--reset")

        self.assertTrue(Transaction.objects.exists())


class SeedTests(TestCase):
    def test_both_members_can_reach_the_app(self):
        demo.seed()

        for username in ("david", "maddie"):
            user = get_user_model().objects.get(username=username)
            self.assertTrue(is_household_member(user))
            self.assertTrue(user.check_password(demo.DEMO_PASSWORD))
            self.assertTrue(TOTPDevice.objects.filter(user=user, confirmed=True).exists())

    def test_the_printed_code_verifies(self):
        demo.seed()

        code = run("demo_totp_code", "maddie").strip()

        self.assertRegex(code, r"^\d{6}$")
        self.assertTrue(TOTPDevice.objects.get(user__username="maddie").verify_token(code))

    def test_every_budget_has_a_current_period_and_a_history(self):
        """What the Today screen's budget widget will read first.

        Spend in the *current* period is not asserted: on the 1st of a month
        a fresh period legitimately has none, and the test would fail then.
        """
        demo.seed()
        today = household_today()

        for budget in Budget.objects.all():
            with self.subTest(budget=budget.name):
                self.assertTrue(
                    BudgetPeriod.objects.filter(
                        budget=budget, period_start__lte=today, period_end__gte=today
                    ).exists()
                )
                periods = BudgetPeriod.objects.filter(budget=budget)
                self.assertEqual(periods.count(), 4)
                self.assertGreater(sum(p.actual_amount for p in periods), 0)

    def test_seeding_twice_is_refused_and_reset_starts_over(self):
        run("seed_household_demo")
        count = Transaction.objects.count()

        with self.assertRaisesMessage(CommandError, "--reset"):
            run("seed_household_demo")

        run("seed_household_demo", "--reset")
        self.assertEqual(Transaction.objects.count(), count)
