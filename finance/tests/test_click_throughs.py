"""Dropdown ordering and the "show me what's behind this number" click-throughs.

Three surfaces feed into the activity list with extra filters: the homepage
budget widget, the Spend chart's bars, and the per-budget attainment bars. All
three are tested here against the same question: does the resulting list
actually match what the number on screen claimed?
"""

from datetime import date, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from finance.models import (
    Account,
    AccountType,
    Budget,
    BudgetPeriod,
    Category,
    Transaction,
)
from finance.services import analytics
from finance.services.rollups import backfill_budget, roll_up_all
from finance.views_transactions import TransactionListView

from .factories import make_account, make_institution, make_transaction
from .test_access import make_user


class CategoryOrderingTests(TestCase):
    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)

    def test_leaf_categories_sort_by_what_is_displayed(self):
        ordered = list(
            Category.objects.filter(is_active=True, children__isnull=True).alphabetical()
        )
        full_paths = [c.full_path for c in ordered]

        self.assertEqual(full_paths, sorted(full_paths, key=str.casefold))

    def test_siblings_land_next_to_each_other(self):
        # Before this, "Food › Coffee" and "Food › Groceries" could be
        # separated by unrelated categories that happened to share a
        # sort_order — the seed resets sort_order to 10, 20, 30… per level.
        ordered = list(
            Category.objects.filter(is_active=True, children__isnull=True).alphabetical()
        )
        coffee_index = next(i for i, c in enumerate(ordered) if c.slug == "food-coffee")
        groceries_index = next(i for i, c in enumerate(ordered) if c.slug == "food-groceries")

        self.assertLessEqual(abs(coffee_index - groceries_index), 3)

    def test_the_review_queue_dropdown_is_alphabetical(self):
        user = make_user("david", with_device=True)
        self.client.force_login(user)
        session = self.client.session
        session["otp_device_id"] = TOTPDevice.objects.get(user=user).persistent_id
        session.save()

        response = self.client.get(reverse("finance:transactions"))
        full_paths = [c.full_path for c in response.context["categories"]]

        self.assertEqual(full_paths, sorted(full_paths, key=str.casefold))

    def test_the_budget_form_dropdown_is_alphabetical(self):
        user = make_user("david", with_device=True)
        self.client.force_login(user)
        session = self.client.session
        session["otp_device_id"] = TOTPDevice.objects.get(user=user).persistent_id
        session.save()

        response = self.client.get(reverse("finance:budget_create"))
        queryset = response.context["form"].fields["categories"].queryset
        names = [c.name for c in queryset]
        groups = [c.parent.name if c.parent else c.name for c in queryset]

        # Grouped alphabetically by top-level name; a parent offered as its
        # own selectable target sorts first within its group, then its
        # children in name order — not naive full-string comparison, since
        # "Financial" would otherwise land in the middle of its own children.
        self.assertEqual(groups, sorted(groups, key=str.casefold))

        for group in set(groups):
            members = [
                (c.parent_id is None, c.name) for c in queryset if
                (c.parent.name if c.parent else c.name) == group
            ]
            anchors = [m for m in members if m[0]]
            children = sorted((m[1] for m in members if not m[0]), key=str.casefold)

            self.assertLessEqual(len(anchors), 1)
            self.assertEqual([m[1] for m in members if not m[0]], children)


class TransactionListFilterTests(TestCase):
    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)

        self.institution = make_institution()
        self.checking = make_account(self.institution, name="Checking")
        self.card = make_account(
            self.institution, name="Card", account_type=AccountType.CREDIT_CARD
        )
        self.groceries = Category.objects.get(slug="food-groceries")
        self.restaurants = Category.objects.get(slug="food-restaurants")
        self.fuel = Category.objects.get(slug="transport-fuel")

        self.budget = Budget.objects.create(name="Food", amount=Decimal("500"))
        self.budget.categories.set([Category.objects.get(slug="food")])

        self.user = make_user("david", with_device=True)
        self.client.force_login(self.user)
        session = self.client.session
        session["otp_device_id"] = TOTPDevice.objects.get(user=self.user).persistent_id
        session.save()

    def spend(self, category, amount="-40.00", account=None, day=15, **kwargs):
        return make_transaction(
            account or self.checking,
            posted_on=date(2026, 4, day),
            amount=Decimal(amount),
            category=category,
            description_raw=f"SPEND {category.slug} {day}",
            **kwargs,
        )

    def get_transactions(self, **params):
        response = self.client.get(reverse("finance:transactions"), params)
        return list(response.context["transactions"])

    def test_budget_filter_matches_what_the_budget_counts_as_spend(self):
        in_budget_1 = self.spend(self.groceries, day=5)
        in_budget_2 = self.spend(self.restaurants, day=6)
        out_of_budget = self.spend(self.fuel, day=7)

        results = self.get_transactions(
            budget=self.budget.pk, start="2026-04-01", end="2026-04-30"
        )

        self.assertEqual({t.pk for t in results}, {in_budget_1.pk, in_budget_2.pk})
        self.assertNotIn(out_of_budget.pk, {t.pk for t in results})

    def test_budget_filter_excludes_transfers_and_inflow_like_the_rollup_does(self):
        self.spend(self.groceries, day=5)
        transfer = self.spend(self.groceries, amount="-100.00", day=6)
        transfer.is_transfer = True
        transfer.save()
        refund = self.spend(self.groceries, amount="30.00", day=7)

        results = self.get_transactions(
            budget=self.budget.pk, start="2026-04-01", end="2026-04-30"
        )
        ids = {t.pk for t in results}

        self.assertNotIn(transfer.pk, ids)
        self.assertNotIn(refund.pk, ids)

    def test_budget_filter_honours_the_budgets_own_account_restriction(self):
        scoped = Budget.objects.create(name="Card only", amount=Decimal("200"))
        scoped.categories.set([Category.objects.get(slug="food")])
        scoped.accounts.set([self.card])

        on_card = self.spend(self.groceries, account=self.card, day=5)
        on_checking = self.spend(self.groceries, account=self.checking, day=6)

        results = self.get_transactions(budget=scoped.pk)

        ids = {t.pk for t in results}
        self.assertIn(on_card.pk, ids)
        self.assertNotIn(on_checking.pk, ids)

    def test_an_invalid_budget_id_degrades_to_no_filter_rather_than_erroring(self):
        response = self.client.get(reverse("finance:transactions"), {"budget": "999999"})
        self.assertEqual(response.status_code, 200)

    def test_a_non_numeric_budget_id_degrades_to_no_filter_rather_than_erroring(self):
        response = self.client.get(reverse("finance:transactions"), {"budget": "abc"})
        self.assertEqual(response.status_code, 200)

    def test_spend_flag_matches_the_dashboards_own_definition(self):
        outflow = self.spend(self.groceries, day=5)
        income_cat = Category.objects.get(slug="income-salary")
        income = self.spend(income_cat, amount="3000.00", day=6)
        transfer = self.spend(self.groceries, amount="-50.00", day=7)
        transfer.is_transfer = True
        transfer.save()

        results = self.get_transactions(spend="1", start="2026-04-01", end="2026-04-30")
        ids = {t.pk for t in results}

        self.assertIn(outflow.pk, ids)
        self.assertNotIn(income.pk, ids)
        self.assertNotIn(transfer.pk, ids)

    def test_multi_value_account_filter(self):
        on_checking = self.spend(self.groceries, account=self.checking, day=5)
        on_card = self.spend(self.groceries, account=self.card, day=6)

        results = self.get_transactions(account=[self.checking.pk, self.card.pk])

        self.assertEqual({t.pk for t in results}, {on_checking.pk, on_card.pk})

    def test_date_range_is_inclusive_on_both_ends(self):
        first = self.spend(self.groceries, day=1)
        last = self.spend(self.groceries, day=30)
        outside = self.spend(self.groceries, day=1, amount="-10.00")
        outside.posted_on = date(2026, 5, 1)
        outside.save()

        results = self.get_transactions(start="2026-04-01", end="2026-04-30")
        ids = {t.pk for t in results}

        self.assertIn(first.pk, ids)
        self.assertIn(last.pk, ids)
        self.assertNotIn(outside.pk, ids)

    def test_an_unparsable_date_is_ignored_rather_than_erroring(self):
        response = self.client.get(
            reverse("finance:transactions"), {"start": "not-a-date"}
        )
        self.assertEqual(response.status_code, 200)

    def test_the_filter_banner_names_the_budget(self):
        response = self.client.get(
            reverse("finance:transactions"), {"budget": self.budget.pk}
        )
        self.assertContains(response, self.budget.name)
        self.assertContains(response, "Clear filter")


class SpendBucketBoundaryTests(TestCase):
    def test_daily_bucket_is_a_single_day(self):
        result = analytics.spend_over_time(
            date(2026, 4, 1), date(2026, 4, 3), grain="daily"
        )
        # No transactions, but the boundary math must not explode on an
        # empty result set.
        self.assertEqual(result["bucket_starts"], [])

    def test_weekly_bucket_spans_monday_to_sunday(self):
        call_command("seed_finance_categories", verbosity=0)
        account = make_account(make_institution(), name="Checking")
        category = Category.objects.get(slug="food-groceries")

        # 6 April 2026 is a Monday.
        Transaction.objects.create(
            account=account, posted_on=date(2026, 4, 8), amount=Decimal("-40.00"),
            description_raw="X", category=category, fingerprint="f1",
        )

        result = analytics.spend_over_time(
            date(2026, 4, 1), date(2026, 4, 30), grain="weekly"
        )

        self.assertEqual(result["bucket_starts"], ["2026-04-06"])
        self.assertEqual(result["bucket_ends"], ["2026-04-12"])

    def test_monthly_bucket_spans_the_whole_calendar_month(self):
        call_command("seed_finance_categories", verbosity=0)
        account = make_account(make_institution(), name="Checking")
        category = Category.objects.get(slug="food-groceries")

        Transaction.objects.create(
            account=account, posted_on=date(2026, 2, 10), amount=Decimal("-40.00"),
            description_raw="X", category=category, fingerprint="f1",
        )

        result = analytics.spend_over_time(
            date(2026, 2, 1), date(2026, 2, 28), grain="monthly"
        )

        # February 2026 is not a leap year -- 28 days, and the boundary math
        # must derive that from calendar.monthrange rather than assuming 30/31.
        self.assertEqual(result["bucket_starts"], ["2026-02-01"])
        self.assertEqual(result["bucket_ends"], ["2026-02-28"])

    def test_a_clicked_buckets_boundaries_reproduce_its_own_total(self):
        """The number on the bar and the sum of what its link shows must match."""
        call_command("seed_finance_categories", verbosity=0)
        account = make_account(make_institution(), name="Checking")
        category = Category.objects.get(slug="food-groceries")

        for day, amount in [(3, "-40.00"), (17, "-60.00"), (28, "-20.00")]:
            Transaction.objects.create(
                account=account, posted_on=date(2026, 4, day), amount=Decimal(amount),
                description_raw="X", category=category, fingerprint=f"f{day}",
            )

        result = analytics.spend_over_time(date(2026, 4, 1), date(2026, 4, 30))
        self.assertEqual(result["values"], [120.0])

        start = date.fromisoformat(result["bucket_starts"][0])
        end = date.fromisoformat(result["bucket_ends"][0])
        matched = analytics.spend_transactions(start, end)

        self.assertEqual(sum(-t.amount for t in matched), Decimal("120.00"))


class SpendChartLinkTests(TestCase):
    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)
        self.user = make_user("david", with_device=True)
        self.client.force_login(self.user)
        session = self.client.session
        session["otp_device_id"] = TOTPDevice.objects.get(user=self.user).persistent_id
        session.save()

        account = make_account(make_institution(), name="Checking")
        category = Category.objects.get(slug="food-groceries")
        self.transaction_date = date(2026, 4, 15)
        Transaction.objects.create(
            account=account, posted_on=self.transaction_date, amount=Decimal("-40.00"),
            description_raw="X", category=category, fingerprint="f1",
        )

    def test_each_bar_gets_a_working_link(self):
        from unittest.mock import patch

        with patch(
            "finance.views_dashboards.household_today",
            return_value=self.transaction_date + timedelta(days=1),
        ):
            response = self.client.get(
                reverse("finance:spend"), {"range": "3m", "grain": "daily"}
            )

        over_time = response.context["over_time_json"]
        self.assertTrue(over_time["values"])
        self.assertEqual(len(over_time["links"]), len(over_time["values"]))

        # Following the first bar's link must reproduce its own number.
        first_link = over_time["links"][0]
        list_response = self.client.get(first_link)
        total = sum(-t.amount for t in list_response.context["transactions"])

        self.assertEqual(float(total), over_time["values"][0])

    def test_an_account_filter_carries_through_to_the_links(self):
        response = self.client.get(
            reverse("finance:spend"), {"range": "3m", "grain": "daily", "account": "1"}
        )

        for link in response.context["over_time_json"]["links"]:
            self.assertIn("account=1", link)


class BudgetHomepageLinkTests(TestCase):
    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)

        self.user = make_user("david", with_device=True)
        self.client.force_login(self.user)
        session = self.client.session
        session["otp_device_id"] = TOTPDevice.objects.get(user=self.user).persistent_id
        session.save()

        institution = make_institution()
        self.account = make_account(institution, name="Checking")
        self.groceries = Category.objects.get(slug="food-groceries")

        self.budget = Budget.objects.create(
            name="Groceries", amount=Decimal("500"),
            anchor_date=date(2026, 4, 1),
        )
        self.budget.categories.set([self.groceries])
        backfill_budget(self.budget, periods_back=1, on_date=date(2026, 4, 15))

        from finance.models import UserPreference

        preference = UserPreference.for_user(self.user)
        preference.homepage_widgets = ["budgets"]
        preference.save()

    def test_the_homepage_link_opens_in_a_new_tab_and_shows_the_right_period(self):
        from unittest.mock import patch

        with patch("finance.services.widgets.household_today", return_value=date(2026, 4, 15)):
            response = self.client.get(reverse("finance:home"))

        self.assertContains(response, 'target="_blank"')
        self.assertContains(response, f"budget={self.budget.pk}")
        self.assertContains(response, "2026-04-01")
        self.assertContains(response, "2026-04-30")
