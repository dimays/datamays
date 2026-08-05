"""Ceilings on how many queries a page is allowed to run.

Not micro-optimization. The point is the *shape* of the growth: a page whose
query count rises with the number of accounts gets slower every time the
household connects one, and nothing in a passing test suite says so.

Charts used to do exactly that — `balance_history()` ran one query per
account to find its pre-window opening balance, and the page called
`balance_history()` three times, so every new account cost three more
queries. Nine accounts meant 71 queries; twenty meant 104.

The ceilings below are deliberately loose. They exist to catch a new N+1,
not to freeze the current number, so raising one by a few is fine when a
page genuinely does more. Raising one *because accounts were added* is the
signal this file is here to give.
"""

from decimal import Decimal

from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from finance.dates import household_today
from finance.models import AccountBalanceSnapshot, Category

from .factories import make_account, make_institution, make_transaction
from .test_access import make_user

# Comfortably above what each page runs today, so ordinary work doesn't trip
# them. See the module docstring for what these are actually protecting.
CEILINGS = {
    "home": 25,
    "transactions": 25,
    "charts": 60,
    "budgets": 20,
    "settings": 30,
}


class QueryCountTestCase(TestCase):
    accounts = 9

    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)

        self.user = make_user("david", with_device=True)
        institution = make_institution()
        groceries = Category.objects.get(slug="food-groceries")

        for index in range(self.accounts):
            account = make_account(institution, name=f"Account {index}")
            AccountBalanceSnapshot.objects.create(
                account=account, as_of=household_today(), current=Decimal("100.00")
            )
            for row in range(20):
                make_transaction(
                    account,
                    amount=Decimal("-10.00"),
                    category=groceries,
                    description_raw=f"TXN {index}-{row}",
                )

        self.client.force_login(self.user)
        session = self.client.session
        session["otp_device_id"] = TOTPDevice.objects.get(user=self.user).persistent_id
        session.save()

    def queries_for(self, url_name):
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(reverse(f"finance:{url_name}"))

        self.assertEqual(response.status_code, 200)
        return len(captured)


class PageQueryCeilingTests(QueryCountTestCase):
    def test_every_page_stays_under_its_ceiling(self):
        for name, ceiling in CEILINGS.items():
            with self.subTest(page=name):
                count = self.queries_for(name)
                self.assertLessEqual(
                    count,
                    ceiling,
                    f"{name} ran {count} queries, ceiling is {ceiling}. "
                    "If this is a genuine new feature, raise the ceiling. "
                    "If it grew with the number of accounts, it's an N+1.",
                )


class QueryCountDoesNotGrowWithAccountsTests(TestCase):
    """The property that actually matters, stated directly.

    Measured by adding accounts rather than rebuilding, so the two readings
    differ in exactly one variable and nothing has to be torn down — the
    category tree can't be deleted anyway (Category.parent is PROTECT).
    """

    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)

        self.user = make_user("david", with_device=True)
        self.institution = make_institution()

        self.client.force_login(self.user)
        session = self.client.session
        session["otp_device_id"] = TOTPDevice.objects.get(user=self.user).persistent_id
        session.save()

    def add_accounts(self, count, offset=0):
        for index in range(count):
            account = make_account(self.institution, name=f"Account {offset + index}")
            AccountBalanceSnapshot.objects.create(
                account=account, as_of=household_today(), current=Decimal("100.00")
            )

    def charts_queries(self):
        with CaptureQueriesContext(connection) as captured:
            self.client.get(reverse("finance:charts"))

        return len(captured)

    def test_charts_costs_the_same_with_four_accounts_as_with_twenty(self):
        self.add_accounts(4)

        # One warm-up request. The very first page view creates this person's
        # UserPreference row, so measuring it would compare a first-ever visit
        # against a routine one and report a difference that has nothing to do
        # with account count.
        self.charts_queries()

        few = self.charts_queries()

        self.add_accounts(16, offset=4)
        many = self.charts_queries()

        self.assertEqual(
            few,
            many,
            f"Charts ran {few} queries with 4 accounts and {many} with 20. "
            "Something on that page is querying once per account.",
        )
