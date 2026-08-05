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
from django.utils.html import escape
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

    def test_budget_filter_excludes_transfers_like_the_rollup_does(self):
        self.spend(self.groceries, day=5)
        transfer = self.spend(self.groceries, amount="-100.00", day=6)
        transfer.is_transfer = True
        transfer.save()

        results = self.get_transactions(
            budget=self.budget.pk, start="2026-04-01", end="2026-04-30"
        )

        self.assertNotIn(transfer.pk, {t.pk for t in results})

    def test_budget_filter_includes_a_refund_like_the_rollup_does(self):
        purchase = self.spend(self.groceries, day=5)
        refund = self.spend(self.groceries, amount="30.00", day=7)

        results = self.get_transactions(
            budget=self.budget.pk, start="2026-04-01", end="2026-04-30"
        )
        ids = {t.pk for t in results}

        self.assertIn(purchase.pk, ids)
        self.assertIn(refund.pk, ids)

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

    def test_resubmitting_the_filter_form_with_no_account_chosen_does_not_error(self):
        # The "All accounts" option in the filter <select> always submits
        # account="" — re-filtering (e.g. after a click-through set other
        # filters) must not try account_id__in=[''].
        response = self.client.get(reverse("finance:transactions"), {"account": ""})
        self.assertEqual(response.status_code, 200)

    def test_filters_combine_with_a_budget_click_through(self):
        in_budget = self.spend(self.groceries, day=5)
        out_of_budget = self.spend(self.fuel, day=6)

        results = self.get_transactions(
            budget=self.budget.pk, start="2026-04-01", end="2026-04-30",
            account="", category="",
        )

        ids = {t.pk for t in results}
        self.assertIn(in_budget.pk, ids)
        self.assertNotIn(out_of_budget.pk, ids)

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
        self.assertContains(response, "Clear all filters")


class BulkCategorizeTests(TestCase):
    """Selecting several transactions at once and setting their category in
    one action, either by explicit id or by reapplying the page's current
    filters to the full matching set."""

    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)

        self.institution = make_institution()
        self.checking = make_account(self.institution, name="Checking")
        self.groceries = Category.objects.get(slug="food-groceries")
        self.restaurants = Category.objects.get(slug="food-restaurants")
        self.uncategorized = Category.objects.get(slug="uncategorized")

        self.user = make_user("david", with_device=True)
        self.client.force_login(self.user)
        session = self.client.session
        session["otp_device_id"] = TOTPDevice.objects.get(user=self.user).persistent_id
        session.save()

    def bulk_post(self, **data):
        data.setdefault("action", "bulk_categorize")
        return self.client.post(reverse("finance:transactions"), data)

    def test_an_explicit_id_list_only_recategorizes_those_transactions(self):
        a = make_transaction(self.checking, category=self.groceries, description_raw="A")
        b = make_transaction(self.checking, category=self.groceries, description_raw="B")
        untouched = make_transaction(self.checking, category=self.groceries, description_raw="C")

        response = self.bulk_post(
            category=self.restaurants.pk, transaction_ids=[a.pk, b.pk]
        )

        self.assertRedirects(response, reverse("finance:transactions"))
        a.refresh_from_db()
        b.refresh_from_db()
        untouched.refresh_from_db()
        self.assertEqual(a.category, self.restaurants)
        self.assertEqual(b.category, self.restaurants)
        self.assertEqual(untouched.category, self.groceries)

    def test_a_bulk_assignment_is_treated_as_a_confirmed_manual_decision(self):
        txn = make_transaction(
            self.checking, category=self.groceries, needs_review=True, description_raw="A"
        )

        self.bulk_post(category=self.restaurants.pk, transaction_ids=[txn.pk])

        txn.refresh_from_db()
        self.assertEqual(txn.category_source, "manual")
        self.assertEqual(txn.category_confidence, 1.0)
        self.assertFalse(txn.needs_review)

    def test_bulk_assigning_to_uncategorized_flags_it_for_review(self):
        txn = make_transaction(
            self.checking, category=self.groceries, needs_review=False, description_raw="A"
        )

        self.bulk_post(category=self.uncategorized.pk, transaction_ids=[txn.pk])

        txn.refresh_from_db()
        self.assertEqual(txn.category, self.uncategorized)
        self.assertTrue(txn.needs_review)

    def test_apply_to_all_filtered_reapplies_the_pages_own_filters(self):
        matching_1 = make_transaction(self.checking, category=self.groceries, description_raw="A")
        matching_2 = make_transaction(self.checking, category=self.groceries, description_raw="B")
        other_account = make_account(self.institution, name="Savings")
        different_account = make_transaction(
            other_account, category=self.groceries, description_raw="C"
        )

        filtered_url = f"{reverse('finance:transactions')}?account={self.checking.pk}"
        response = self.client.post(
            filtered_url,
            {
                "action": "bulk_categorize",
                "category": self.restaurants.pk,
                "apply_to_all_filtered": "1",
            },
        )

        self.assertRedirects(response, filtered_url)
        matching_1.refresh_from_db()
        matching_2.refresh_from_db()
        different_account.refresh_from_db()
        self.assertEqual(matching_1.category, self.restaurants)
        self.assertEqual(matching_2.category, self.restaurants)
        self.assertEqual(different_account.category, self.groceries)

    def test_an_empty_id_list_recategorizes_nothing(self):
        txn = make_transaction(self.checking, category=self.groceries, description_raw="A")

        response = self.bulk_post(category=self.restaurants.pk, transaction_ids=[])

        self.assertRedirects(response, reverse("finance:transactions"))
        txn.refresh_from_db()
        self.assertEqual(txn.category, self.groceries)

    def test_bulk_categorize_is_gated_like_everything_else(self):
        self.client.logout()

        response = self.bulk_post(category=self.restaurants.pk, transaction_ids=[])

        self.assertEqual(response.status_code, 403)


class PaginationPreservesFiltersTests(TestCase):
    """A page-2 link used to be a bare "?page=2", silently dropping every
    other active filter — most confusingly review=1, which made "next page"
    from the review queue look like it dumped you into the full activity
    list."""

    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)

        self.institution = make_institution()
        self.checking = make_account(self.institution, name="Checking")
        self.groceries = Category.objects.get(slug="food-groceries")

        for i in range(55):
            make_transaction(
                self.checking,
                needs_review=True,
                category=Category.objects.get(slug="uncategorized"),
                description_raw=f"NEEDS REVIEW {i}",
                posted_on=date(2026, 4, 1) + timedelta(days=i % 20),
            )

        self.user = make_user("david", with_device=True)
        self.client.force_login(self.user)
        session = self.client.session
        session["otp_device_id"] = TOTPDevice.objects.get(user=self.user).persistent_id
        session.save()

    def test_the_next_page_link_carries_the_review_filter_forward(self):
        response = self.client.get(reverse("finance:transactions"), {"review": "1"})

        # Both on the SAME link's query string, not just present somewhere
        # on the page — checked against the actual URL the view built,
        # rather than against HTML-escaped page content.
        self.assertIn("review=1", response.context["next_page_url"])
        self.assertIn("page=2", response.context["next_page_url"])
        self.assertContains(response, escape(response.context["next_page_url"]))

    def test_the_next_page_link_carries_an_account_filter_forward(self):
        response = self.client.get(
            reverse("finance:transactions"), {"account": self.checking.pk}
        )

        self.assertIn(f"account={self.checking.pk}", response.context["next_page_url"])
        self.assertIn("page=2", response.context["next_page_url"])

    def test_the_last_page_has_no_next_link(self):
        response = self.client.get(reverse("finance:transactions"), {"page": 2})

        self.assertIsNone(response.context["next_page_url"])
        self.assertIn("page=1", response.context["previous_page_url"])


class SelectAllTests(TestCase):
    """Selecting everything shouldn't require clicking each row first."""

    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)

        self.institution = make_institution()
        self.checking = make_account(self.institution, name="Checking")
        self.groceries = Category.objects.get(slug="food-groceries")

        self.user = make_user("david", with_device=True)
        self.client.force_login(self.user)
        session = self.client.session
        session["otp_device_id"] = TOTPDevice.objects.get(user=self.user).persistent_id
        session.save()

    def test_a_select_all_on_page_control_is_always_present(self):
        make_transaction(self.checking, category=self.groceries, description_raw="A")

        response = self.client.get(reverse("finance:transactions"))

        self.assertContains(response, "Select all on this page")

    def test_the_select_all_filtered_control_does_not_require_a_prior_selection(self):
        for i in range(55):
            make_transaction(
                self.checking,
                category=self.groceries,
                description_raw=f"TXN {i}",
                posted_on=date(2026, 4, 1) + timedelta(days=i % 20),
            )

        response = self.client.get(reverse("finance:transactions"))
        body = response.content.decode()

        # Not nested inside the x-show="selected.length > 0 ..." toolbar --
        # it must render in markup regardless of Alpine's runtime state.
        self.assertIn("Select all 55 matching this filter", body)

    def test_no_select_all_filtered_control_when_everything_fits_on_one_page(self):
        make_transaction(self.checking, category=self.groceries, description_raw="A")

        response = self.client.get(reverse("finance:transactions"))

        # Distinct from the toolbar's always-in-markup (merely hidden)
        # "All N matching this filter" status text, which lacks "Select all".
        self.assertNotContains(response, "Select all 1 matching this filter")

    def test_row_checkboxes_visually_reflect_select_all_filtered(self):
        # Previously bound with x-model, which only ever reflected the
        # per-id `selected` array — checking "select all N matching this
        # filter" left every row checkbox looking unchecked even though the
        # bulk-apply itself correctly targeted the whole filtered set.
        make_transaction(self.checking, category=self.groceries, description_raw="A")

        response = self.client.get(reverse("finance:transactions"))
        body = response.content.decode()

        self.assertIn(':checked="selectAllFiltered || selected.includes(', body)
        self.assertIn(':disabled="selectAllFiltered"', body)


class MultiSelectFilterTests(TestCase):
    """Accounts, categories, and budgets are all multi-select: OR within one
    filter, AND across different filters — the standard faceted-search
    convention. Budgets specifically union (any of the selected budgets'
    categories/accounts count), since "show me these two budgets" means
    "everything either one counts," not "only what both count.\""""

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

        self.groceries_budget = Budget.objects.create(name="Groceries", amount=Decimal("500"))
        self.groceries_budget.categories.set([self.groceries])

        self.fuel_budget = Budget.objects.create(name="Fuel", amount=Decimal("200"))
        self.fuel_budget.categories.set([self.fuel])

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

    def get(self, **params):
        return self.client.get(reverse("finance:transactions"), params)

    def get_transactions(self, **params):
        return list(self.get(**params).context["transactions"])

    def test_multiple_categories_are_ored_together(self):
        groceries_txn = self.spend(self.groceries, day=5)
        restaurants_txn = self.spend(self.restaurants, day=6)
        fuel_txn = self.spend(self.fuel, day=7)

        results = self.get_transactions(
            category=[self.groceries.pk, self.restaurants.pk]
        )
        ids = {t.pk for t in results}

        self.assertEqual(ids, {groceries_txn.pk, restaurants_txn.pk})
        self.assertNotIn(fuel_txn.pk, ids)

    def test_multiple_budgets_union_rather_than_intersect(self):
        groceries_txn = self.spend(self.groceries, day=5)
        fuel_txn = self.spend(self.fuel, day=6)
        restaurants_txn = self.spend(self.restaurants, day=7)

        results = self.get_transactions(
            budget=[self.groceries_budget.pk, self.fuel_budget.pk]
        )
        ids = {t.pk for t in results}

        self.assertEqual(ids, {groceries_txn.pk, fuel_txn.pk})
        self.assertNotIn(restaurants_txn.pk, ids)

    def test_a_budget_and_an_account_filter_still_and_together(self):
        on_checking = self.spend(self.groceries, account=self.checking, day=5)
        on_card = self.spend(self.groceries, account=self.card, day=6)

        results = self.get_transactions(
            budget=self.groceries_budget.pk, account=self.card.pk
        )
        ids = {t.pk for t in results}

        self.assertEqual(ids, {on_card.pk})
        self.assertNotIn(on_checking.pk, ids)

    def test_a_budget_and_a_non_overlapping_category_yield_no_results_not_an_error(self):
        # Groceries budget only covers the groceries category, so asking for
        # it *and* fuel is a legitimate, well-defined request that happens to
        # match nothing -- narrowing, not widening.
        self.spend(self.groceries, day=5)

        response = self.get(budget=self.groceries_budget.pk, category=self.fuel.pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["transactions"]), [])
        self.assertContains(response, "No transactions match these filters")
        self.assertTrue(response.context["has_active_filters"])

    def test_the_banner_lists_every_active_filter_dimension(self):
        response = self.get(
            budget=self.groceries_budget.pk,
            category=self.restaurants.pk,
            account=self.checking.pk,
        )

        self.assertContains(response, self.groceries_budget.name)
        self.assertContains(response, self.restaurants.full_path)
        self.assertContains(response, self.checking.name)

    def test_no_filters_active_shows_the_plain_empty_state(self):
        response = self.get()

        self.assertFalse(response.context["has_active_filters"])
        self.assertContains(response, "No transactions yet.")


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
                reverse("finance:charts"), {"range": "3m", "grain": "weekly"}
            )

        over_time = response.context["spend_over_time_json"]
        self.assertTrue(over_time["values"])
        self.assertEqual(len(over_time["links"]), len(over_time["values"]))

        # Following the first bar's link must reproduce its own number.
        first_link = over_time["links"][0]
        list_response = self.client.get(first_link)
        total = sum(-t.amount for t in list_response.context["transactions"])

        self.assertEqual(float(total), over_time["values"][0])

    def test_an_account_filter_carries_through_to_the_links(self):
        response = self.client.get(
            reverse("finance:charts"), {"range": "3m", "grain": "weekly", "account": "1"}
        )

        for link in response.context["spend_over_time_json"]["links"]:
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
