"""Budget rollups: what counts toward a budget, and what must not."""

from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from finance.models import (
    AccountType,
    Budget,
    BudgetPeriod,
    BudgetPeriodType,
    Category,
)
from finance.services.rollups import (
    backfill_budget,
    expand_categories,
    roll_up_all,
    roll_up_budget,
    spend_for,
)

from .factories import make_account, make_institution, make_transaction
from .test_access import make_user


class RollupTestCase(TestCase):
    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)

        self.institution = make_institution()
        self.checking = make_account(self.institution, name="Checking")
        self.card = make_account(
            self.institution, name="Card", account_type=AccountType.CREDIT_CARD
        )

        self.food = Category.objects.get(slug="food")
        self.groceries = Category.objects.get(slug="food-groceries")
        self.restaurants = Category.objects.get(slug="food-restaurants")
        self.fuel = Category.objects.get(slug="transport-fuel")

    def make_budget(self, categories=None, accounts=None, **kwargs):
        kwargs.setdefault("name", "Food")
        kwargs.setdefault("amount", Decimal("800.00"))
        kwargs.setdefault("anchor_date", date(2026, 4, 1))

        budget = Budget.objects.create(**kwargs)
        budget.categories.set(categories or [self.groceries])

        if accounts:
            budget.accounts.set(accounts)

        return budget

    def spend(self, amount, category, account=None, day=15):
        return make_transaction(
            account or self.checking,
            posted_on=date(2026, 4, day),
            amount=Decimal(amount),
            description_raw=f"SPEND {category.slug} {day} {amount}",
            category=category,
        )


class CategoryExpansionTests(RollupTestCase):
    def test_choosing_a_parent_includes_its_children(self):
        expanded = expand_categories([self.food])

        self.assertIn(self.groceries.pk, expanded)
        self.assertIn(self.restaurants.pk, expanded)

    def test_choosing_a_leaf_stays_narrow(self):
        expanded = expand_categories([self.groceries])

        self.assertEqual(expanded, [self.groceries.pk])

    def test_a_budget_on_food_counts_groceries_and_restaurants(self):
        budget = self.make_budget(categories=[self.food])
        self.spend("-100.00", self.groceries)
        self.spend("-60.00", self.restaurants, day=16)
        self.spend("-40.00", self.fuel, day=17)

        self.assertEqual(spend_for(budget, date(2026, 4, 1), date(2026, 4, 30)), Decimal("160.00"))


class SpendCalculationTests(RollupTestCase):
    def test_only_outflow_counts(self):
        budget = self.make_budget()
        self.spend("-100.00", self.groceries)

        period = roll_up_budget(budget, date(2026, 4, 20))

        self.assertEqual(period.actual_amount, Decimal("100.00"))

    def test_a_refund_reduces_the_total(self):
        budget = self.make_budget()
        self.spend("-100.00", self.groceries)
        self.spend("30.00", self.groceries, day=16)

        # Signed sum, so the refund nets off rather than being ignored.
        period = roll_up_budget(budget, date(2026, 4, 20))
        self.assertEqual(period.actual_amount, Decimal("70.00"))

    def test_a_refund_bigger_than_the_periods_spend_floors_at_zero(self):
        budget = self.make_budget()
        self.spend("-20.00", self.groceries)
        self.spend("50.00", self.groceries, day=16)

        period = roll_up_budget(budget, date(2026, 4, 20))

        self.assertEqual(period.actual_amount, Decimal("0"))

    def test_a_refund_in_a_later_period_does_not_retroactively_adjust_the_earlier_one(self):
        budget = self.make_budget()
        self.spend("-100.00", self.groceries, day=20)  # April: the purchase

        april = roll_up_budget(budget, date(2026, 4, 20))
        self.assertEqual(april.actual_amount, Decimal("100.00"))

        make_transaction(
            self.checking,
            posted_on=date(2026, 5, 5),
            amount=Decimal("100.00"),
            description_raw="REFUND",
            category=self.groceries,
        )
        may = roll_up_budget(budget, date(2026, 5, 20))

        # April still reads as spent -- rollups are computed per period from
        # what posted in that period's own window, not retroactively matched
        # back to the original purchase.
        april.refresh_from_db()
        self.assertEqual(april.actual_amount, Decimal("100.00"))
        self.assertEqual(may.actual_amount, Decimal("0"))

    def test_transfers_never_count(self):
        budget = self.make_budget()
        self.spend("-100.00", self.groceries)

        transfer = self.spend("-500.00", self.groceries, day=16)
        transfer.is_transfer = True
        transfer.save()

        period = roll_up_budget(budget, date(2026, 4, 20))

        # Counting a transfer would make every budget look blown.
        self.assertEqual(period.actual_amount, Decimal("100.00"))

    def test_spend_outside_the_period_is_excluded(self):
        budget = self.make_budget()
        self.spend("-100.00", self.groceries, day=15)
        make_transaction(
            self.checking,
            posted_on=date(2026, 3, 20),
            amount=Decimal("-999.00"),
            description_raw="LAST MONTH",
            category=self.groceries,
        )

        period = roll_up_budget(budget, date(2026, 4, 20))

        self.assertEqual(period.actual_amount, Decimal("100.00"))

    def test_an_account_filter_narrows_the_total(self):
        budget = self.make_budget(accounts=[self.card])
        self.spend("-100.00", self.groceries, account=self.checking)
        self.spend("-60.00", self.groceries, account=self.card, day=16)

        period = roll_up_budget(budget, date(2026, 4, 20))

        self.assertEqual(period.actual_amount, Decimal("60.00"))

    def test_no_account_filter_counts_every_account(self):
        budget = self.make_budget()
        self.spend("-100.00", self.groceries, account=self.checking)
        self.spend("-60.00", self.groceries, account=self.card, day=16)

        period = roll_up_budget(budget, date(2026, 4, 20))

        self.assertEqual(period.actual_amount, Decimal("160.00"))

    def test_a_budget_with_no_categories_spends_nothing(self):
        budget = Budget.objects.create(name="Empty", amount=Decimal("100"))
        self.spend("-100.00", self.groceries)

        self.assertEqual(spend_for(budget, date(2026, 4, 1), date(2026, 4, 30)), Decimal("0"))


class PaceTests(RollupTestCase):
    def test_pace_flags_spending_too_fast_early_in_the_period(self):
        budget = self.make_budget()
        self.spend("-600.00", self.groceries, day=8)

        period = roll_up_budget(budget, date(2026, 4, 8))

        # $600 of an $800 budget by the 8th is well ahead of an even pace.
        self.assertGreater(period.pace_difference(date(2026, 4, 8)), Decimal("350"))

    def test_the_same_spend_is_comfortable_late_in_the_period(self):
        budget = self.make_budget()
        self.spend("-600.00", self.groceries, day=8)

        period = roll_up_budget(budget, date(2026, 4, 30))

        self.assertLess(period.pace_difference(date(2026, 4, 30)), Decimal("0"))

    def test_the_progress_bar_cannot_overflow(self):
        budget = self.make_budget(amount=Decimal("100.00"))
        self.spend("-500.00", self.groceries)

        period = roll_up_budget(budget, date(2026, 4, 20))

        self.assertTrue(period.is_over)
        self.assertEqual(period.bar_width, 100)
        self.assertEqual(period.overspend, Decimal("400.00"))


class RolloverTests(RollupTestCase):
    def test_an_underspend_increases_next_period(self):
        budget = self.make_budget(rollover=True)

        BudgetPeriod.objects.create(
            budget=budget,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            target_amount=Decimal("800.00"),
            actual_amount=Decimal("600.00"),
        )

        period = roll_up_budget(budget, date(2026, 4, 15))

        self.assertEqual(period.rollover_amount, Decimal("200.00"))
        self.assertEqual(period.target_amount, Decimal("1000.00"))

    def test_an_overspend_reduces_next_period(self):
        budget = self.make_budget(rollover=True)

        BudgetPeriod.objects.create(
            budget=budget,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            target_amount=Decimal("800.00"),
            actual_amount=Decimal("950.00"),
        )

        period = roll_up_budget(budget, date(2026, 4, 15))

        self.assertEqual(period.target_amount, Decimal("650.00"))

    def test_rollover_off_means_a_clean_slate(self):
        budget = self.make_budget(rollover=False)

        BudgetPeriod.objects.create(
            budget=budget,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            target_amount=Decimal("800.00"),
            actual_amount=Decimal("950.00"),
        )

        period = roll_up_budget(budget, date(2026, 4, 15))

        self.assertEqual(period.target_amount, Decimal("800.00"))


class IdempotencyTests(RollupTestCase):
    def test_re_running_updates_rather_than_duplicating(self):
        budget = self.make_budget()
        self.spend("-100.00", self.groceries)

        roll_up_budget(budget, date(2026, 4, 20))
        roll_up_budget(budget, date(2026, 4, 20))

        self.assertEqual(budget.budget_periods.count(), 1)

    def test_later_spend_updates_the_same_period(self):
        budget = self.make_budget()
        self.spend("-100.00", self.groceries)
        roll_up_budget(budget, date(2026, 4, 20))

        self.spend("-50.00", self.groceries, day=18)
        period = roll_up_budget(budget, date(2026, 4, 20))

        self.assertEqual(budget.budget_periods.count(), 1)
        self.assertEqual(period.actual_amount, Decimal("150.00"))

    def test_paused_budgets_are_skipped(self):
        self.make_budget(is_active=False)

        self.assertEqual(len(roll_up_all(date(2026, 4, 20))), 0)
        self.assertEqual(len(roll_up_all(date(2026, 4, 20), include_inactive=True)), 1)

    def test_weekly_budgets_resolve_their_own_window(self):
        budget = self.make_budget(
            period_type=BudgetPeriodType.WEEKLY, anchor_date=date(2026, 4, 6)
        )
        self.spend("-40.00", self.groceries, day=8)

        period = roll_up_budget(budget, date(2026, 4, 8))

        self.assertEqual(period.period_start, date(2026, 4, 6))
        self.assertEqual(period.period_end, date(2026, 4, 12))
        self.assertEqual(period.actual_amount, Decimal("40.00"))


class BackfillTests(RollupTestCase):
    def test_backfill_creates_history_for_a_new_budget(self):
        budget = self.make_budget()

        periods = backfill_budget(budget, periods_back=5, on_date=date(2026, 4, 20))

        self.assertEqual(len(periods), 6)
        self.assertEqual(budget.budget_periods.count(), 6)

    def test_backfill_runs_oldest_first_so_rollover_chains_correctly(self):
        budget = self.make_budget(rollover=True)

        periods = backfill_budget(budget, periods_back=3, on_date=date(2026, 4, 20))

        starts = [period.period_start for period in periods]
        self.assertEqual(starts, sorted(starts))


class BudgetViewTests(RollupTestCase):
    def setUp(self):
        super().setUp()
        self.user = make_user("david", with_device=True)
        self.client.force_login(self.user)

        from django_otp.plugins.otp_totp.models import TOTPDevice

        session = self.client.session
        session["otp_device_id"] = TOTPDevice.objects.get(user=self.user).persistent_id
        session.save()

    def test_the_list_renders(self):
        self.make_budget()
        roll_up_all()

        response = self.client.get(reverse("finance:budgets"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Food")

    def test_creating_a_budget_backfills_history(self):
        response = self.client.post(
            reverse("finance:budget_create"),
            {
                "name": "Groceries",
                "amount": "800.00",
                "period_type": "monthly",
                "anchor_date": "2026-04-01",
                "categories": [self.groceries.pk],
                "is_active": "on",
            },
        )

        self.assertRedirects(response, reverse("finance:budgets"))

        budget = Budget.objects.get(name="Groceries")
        self.assertGreater(budget.budget_periods.count(), 1)

    def test_a_budget_needs_at_least_one_category(self):
        response = self.client.post(
            reverse("finance:budget_create"),
            {
                "name": "Nothing",
                "amount": "100.00",
                "period_type": "monthly",
                "anchor_date": "2026-04-01",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Budget.objects.filter(name="Nothing").exists())

    def test_editing_recomputes_the_current_period(self):
        budget = self.make_budget()
        self.spend("-100.00", self.groceries)
        self.spend("-60.00", self.restaurants, day=16)
        roll_up_budget(budget)

        self.client.post(
            reverse("finance:budget_edit", args=[budget.pk]),
            {
                "name": budget.name,
                "amount": "800.00",
                "period_type": "monthly",
                "anchor_date": "2026-04-01",
                "categories": [self.groceries.pk, self.restaurants.pk],
                "is_active": "on",
            },
        )

        period = budget.budget_periods.order_by("-period_start").first()
        self.assertIsNotNone(period)

    def test_income_categories_are_not_offered_as_budget_targets(self):
        response = self.client.get(reverse("finance:budget_create"))
        form = response.context["form"]

        slugs = {category.slug for category in form.fields["categories"].queryset}

        self.assertIn("food-groceries", slugs)
        self.assertNotIn("income-salary", slugs)
        self.assertNotIn("transfer-internal", slugs)
