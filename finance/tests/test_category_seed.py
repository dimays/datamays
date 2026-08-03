from django.core.management import call_command
from django.test import TestCase

from finance.categories_seed import (
    CARD_PAYMENT_SLUG,
    TRANSFER_SLUG,
    UNCATEGORIZED_SLUG,
)
from finance.models import MAX_CATEGORY_DEPTH, Category, CategoryKind


class SeedCategoriesTests(TestCase):
    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)

    def test_the_tree_is_created(self):
        self.assertGreater(Category.objects.count(), 50)
        self.assertTrue(Category.objects.filter(parent__isnull=True).exists())

    def test_slugs_the_code_depends_on_exist_and_are_protected(self):
        for slug in [UNCATEGORIZED_SLUG, TRANSFER_SLUG, CARD_PAYMENT_SLUG]:
            with self.subTest(slug=slug):
                category = Category.objects.get(slug=slug)
                self.assertTrue(category.is_system)

    def test_children_inherit_their_parent_kind(self):
        for category in Category.objects.filter(parent__isnull=False).select_related("parent"):
            with self.subTest(category=category.slug):
                self.assertEqual(category.kind, category.parent.kind)

    def test_transfers_are_kind_transfer_so_they_leave_spend_totals(self):
        self.assertEqual(
            Category.objects.get(slug=TRANSFER_SLUG).kind, CategoryKind.TRANSFER
        )

    def test_income_categories_exist_for_the_income_dashboard(self):
        self.assertTrue(
            Category.objects.filter(kind=CategoryKind.INCOME, parent__isnull=False).exists()
        )

    def test_nothing_exceeds_the_depth_cap(self):
        for category in Category.objects.all():
            with self.subTest(category=category.slug):
                self.assertLessEqual(category.depth, MAX_CATEGORY_DEPTH)

    def test_every_leaf_has_a_description_to_steer_the_classifier(self):
        leaves = Category.objects.filter(children__isnull=True)

        for category in leaves:
            with self.subTest(category=category.slug):
                self.assertTrue(category.description, f"{category.slug} has no description")

    def test_rerunning_is_idempotent(self):
        before = Category.objects.count()

        call_command("seed_finance_categories", verbosity=0)

        self.assertEqual(Category.objects.count(), before)

    def test_rerunning_does_not_disturb_categories_you_added(self):
        custom = Category.objects.create(name="Boat Fund", slug="boat-fund")

        call_command("seed_finance_categories", verbosity=0)

        self.assertTrue(Category.objects.filter(pk=custom.pk).exists())
