"""Uncategorized is not spend; "Uncategorized Spend" is.

Found 2026-10-12 in production: the categorizer parked new-format paychecks
and a $19,200 loan payoff to a credit card in the expense-kind Uncategorized
category, so they were netted against spending as refunds and September read
-$11,116.60.
"""

from datetime import date
from decimal import Decimal
from importlib import import_module

from django.apps import apps
from django.core.management import call_command
from django.test import TestCase

from finance.categories_seed import UNCATEGORIZED_SLUG, UNCATEGORIZED_SPEND_SLUG
from finance.forms.budgets import BudgetForm
from finance.forms.categories import CategoryForm
from finance.models import Category, CategoryKind, Transaction
from finance.services.analytics import spend_filter
from finance.services.categorize import category_catalogue

from .factories import make_account, make_transaction

DAY = date(2026, 9, 22)


class SpendTests(TestCase):
    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)
        self.account = make_account()
        self.uncategorized = Category.objects.get(slug=UNCATEGORIZED_SLUG)
        self.uncategorized_spend = Category.objects.get(slug=UNCATEGORIZED_SPEND_SLUG)

    def spend(self):
        return -sum(Transaction.objects.filter(spend_filter()).values_list("amount", flat=True), Decimal("0"))

    def test_money_parked_in_uncategorized_is_not_a_refund(self):
        make_transaction(account=self.account, posted_on=DAY, amount=Decimal("-100.00"),
                         category=Category.objects.get(slug="food-groceries"))
        make_transaction(account=self.account, posted_on=DAY, amount=Decimal("19200.00"),
                         category=self.uncategorized, description_raw="Electronic Payment")

        self.assertEqual(self.spend(), Decimal("100.00"))

    def test_nor_is_an_outflow_parked_there_spend_until_someone_says_so(self):
        make_transaction(account=self.account, posted_on=DAY, amount=Decimal("-40.00"), category=self.uncategorized)

        self.assertEqual(self.spend(), Decimal("0"))

    def test_uncategorized_spend_counts(self):
        make_transaction(account=self.account, posted_on=DAY, amount=Decimal("-40.00"),
                         category=self.uncategorized_spend)

        self.assertEqual(self.spend(), Decimal("40.00"))

    def test_the_kinds_are_as_seeded(self):
        self.assertEqual(self.uncategorized.kind, CategoryKind.UNCLASSIFIED)
        self.assertEqual(self.uncategorized_spend.kind, CategoryKind.EXPENSE)
        self.assertTrue(self.uncategorized_spend.is_system)

    def test_only_a_person_chooses_uncategorized_spend(self):
        slugs = {category["slug"] for category in category_catalogue()}

        self.assertNotIn(UNCATEGORIZED_SPEND_SLUG, slugs)
        self.assertIn(UNCATEGORIZED_SLUG, slugs)

    def test_a_budget_can_include_uncategorized_spend_but_not_uncategorized(self):
        choices = BudgetForm().fields["categories"].queryset

        self.assertIn(self.uncategorized_spend, choices)
        self.assertNotIn(self.uncategorized, choices)

    def test_nobody_makes_another_unclassified_category(self):
        kinds = [value for value, _ in CategoryForm().fields["kind"].choices]

        self.assertNotIn(CategoryKind.UNCLASSIFIED, kinds)
        self.assertTrue(CategoryForm(instance=self.uncategorized).fields["kind"].disabled)


class MigrationTests(TestCase):
    """The data migration, run against a database seeded the old way."""

    migration = import_module("finance.migrations.0012_uncategorized_is_not_spend")

    def setUp(self):
        # The test database was built by running this migration; start from
        # the state it found in production instead.
        Category.objects.filter(slug__in=[UNCATEGORIZED_SLUG, UNCATEGORIZED_SPEND_SLUG]).delete()
        Category.objects.create(name="Uncategorized", slug=UNCATEGORIZED_SLUG,
                                kind=CategoryKind.EXPENSE, is_system=True, sort_order=150)

    def test_forwards_reclassifies_and_adds_the_spend_category(self):
        self.migration.forwards(apps, None)
        self.migration.forwards(apps, None)  # and again, harmlessly

        self.assertEqual(Category.objects.get(slug=UNCATEGORIZED_SLUG).kind, CategoryKind.UNCLASSIFIED)
        spend = Category.objects.get(slug=UNCATEGORIZED_SPEND_SLUG)
        self.assertEqual((spend.kind, spend.is_system, spend.sort_order), (CategoryKind.EXPENSE, True, 149))

    def test_backwards_restores_the_old_kind(self):
        self.migration.forwards(apps, None)
        self.migration.backwards(apps, None)

        self.assertEqual(Category.objects.get(slug=UNCATEGORIZED_SLUG).kind, CategoryKind.EXPENSE)
