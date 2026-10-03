"""The finance bridge: project budgets, linked spending, job purchases, and
projected maintenance costs.

Real finance rows throughout (built with finance's own test factories), so
the sign convention and finance's definition of spend are exercised, not
assumed.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from finance.models import Category
from finance.tests.factories import make_account, make_transaction
from household.dates import household_timezone, household_today
from household.integrations import finance
from household.models import BudgetLine, Chore, MaintenanceItem, OccurrenceStatus, Project, ProjectExpense, ProjectStatus
from household.scheduling import Anchor, Frequency
from household.services import maintenance, occurrences, spending

from .factories import make_member, sign_in

TODAY = date(2026, 9, 30)


def category(slug):
    return Category.objects.get(slug=slug)


class SpendingTestCase(TestCase):
    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)
        self.account = make_account(name="Rewards Card")
        self.david = make_member("david", first_name="David")

    def txn(self, amount, *, days_ago=5, slug="housing-improvement", merchant="Home Center", **fields):
        return make_transaction(
            self.account,
            amount=Decimal(amount),
            posted_on=household_today() - timedelta(days=days_ago),
            description_raw=merchant.upper(),
            merchant=merchant,
            category=category(slug) if slug else None,
            **fields,
        )


class SignTests(SpendingTestCase):
    def test_a_purchase_spends_a_positive_amount_and_a_refund_nets_back(self):
        purchase = self.txn("-412.87")
        refund = self.txn("20.00")

        self.assertEqual(finance.spent(purchase), Decimal("412.87"))
        self.assertEqual(finance.spent(refund), Decimal("-20.00"))
        self.assertEqual(finance.total_spent([purchase, refund]), Decimal("392.87"))


class BudgetSummaryTests(SpendingTestCase):
    def setUp(self):
        super().setUp()
        self.project = Project.objects.create(name="Kitchen", status=ProjectStatus.ACTIVE,
                                              budget_total=Decimal("1000.00"))
        self.paint = BudgetLine.objects.create(project=self.project, label="Paint", estimated=Decimal("300.00"))
        self.tile = BudgetLine.objects.create(project=self.project, label="Tile", estimated=Decimal("500.00"))

    def test_actuals_reconcile_to_the_cent(self):
        spending.link_expense(self.project, self.txn("-123.45").pk, self.paint.pk)
        spending.link_expense(self.project, self.txn("-200.01").pk, self.paint.pk)
        spending.link_expense(self.project, self.txn("-99.99").pk, self.tile.pk)
        spending.link_expense(self.project, self.txn("-10.00").pk)  # no line
        spending.link_expense(self.project, self.txn("15.00").pk, self.paint.pk)  # a refund

        summary = spending.budget_summary(self.project)
        by_label = {row.line.label: row for row in summary.lines}

        self.assertEqual(by_label["Paint"].actual, Decimal("308.46"))
        self.assertTrue(by_label["Paint"].is_over)
        self.assertEqual(by_label["Tile"].actual, Decimal("99.99"))
        self.assertEqual(summary.unassigned, Decimal("10.00"))
        self.assertEqual(summary.actual, Decimal("418.45"))
        self.assertEqual(summary.actual, sum(row.actual for row in summary.lines) + summary.unassigned)
        self.assertEqual(summary.estimated, Decimal("800.00"))
        self.assertEqual(summary.remaining, Decimal("581.55"))
        self.assertFalse(summary.is_over)

    def test_without_an_overall_budget_the_lines_are_the_target(self):
        self.project.budget_total = None
        spending.link_expense(self.project, self.txn("-900.00").pk)

        summary = spending.budget_summary(self.project)

        self.assertEqual(summary.target, Decimal("800.00"))
        self.assertTrue(summary.is_over)
        self.assertEqual(summary.percent, 100)

    def test_linking_is_idempotent_and_validated(self):
        purchase = self.txn("-50.00")
        other_project_line = BudgetLine.objects.create(
            project=Project.objects.create(name="Garden"), label="Seeds", estimated=Decimal("20")
        )

        first = spending.link_expense(self.project, purchase.pk, self.paint.pk)
        again = spending.link_expense(self.project, purchase.pk, self.tile.pk)
        foreign_line = spending.link_expense(self.project, self.txn("-5.00").pk, other_project_line.pk)

        self.assertEqual(first.pk, again.pk)
        self.assertEqual(ProjectExpense.objects.filter(transaction=purchase).count(), 1)
        self.assertIsNone(foreign_line.budget_line)
        self.assertIsNone(spending.link_expense(self.project, 999999))
        self.assertIsNone(spending.link_expense(self.project, "not-a-number"))

    def test_a_deleted_transaction_stops_counting(self):
        purchase = self.txn("-50.00")
        spending.link_expense(self.project, purchase.pk)

        purchase.delete()

        self.assertEqual(spending.budget_summary(self.project).actual, Decimal("0"))


class CandidateTests(SpendingTestCase):
    def setUp(self):
        super().setUp()
        self.project = Project.objects.create(name="Kitchen", start_on=household_today() - timedelta(days=20))

    def titles(self, query=""):
        return [txn.merchant for txn in spending.project_candidates(self.project, household_today(), query)]

    def test_suggestions_are_home_spend_in_the_window(self):
        self.txn("-40.00", merchant="Home Center")
        self.txn("-60.00", merchant="Furniture Barn", slug="housing-furnishings")
        self.txn("-30.00", merchant="Fresh Market", slug="food-groceries")
        self.txn("-500.00", merchant="Card payment", is_transfer=True)
        self.txn("3150.00", merchant="Acme Payroll", slug="income-salary")
        self.txn("-40.00", merchant="Too early", days_ago=200)

        self.assertEqual(sorted(self.titles()), ["Furniture Barn", "Home Center"])

    def test_a_search_reaches_every_category_but_still_only_spend(self):
        self.txn("-30.00", merchant="Tile Depot", slug="shopping-general")
        self.txn("-25.00", merchant="Tile Depot", slug="food-restaurants")
        self.txn("-500.00", merchant="Tile Depot transfer", is_transfer=True)

        self.assertEqual(len(self.titles("tile depot")), 2)

    def test_already_linked_purchases_are_not_suggested_again(self):
        purchase = self.txn("-40.00")
        spending.link_expense(self.project, purchase.pk)

        self.assertEqual(self.titles(), [])

    def test_a_refund_shows_as_negative_spend_not_a_mangled_number(self):
        self.txn("12.34", merchant="Home Center refund")

        [refund] = spending.project_candidates(self.project, household_today())

        self.assertEqual(refund.spent, Decimal("-12.34"))


class ProjectViewTests(SpendingTestCase):
    def setUp(self):
        super().setUp()
        sign_in(self.client, self.david)
        self.project = Project.objects.create(name="Kitchen", status=ProjectStatus.ACTIVE)
        self.line = BudgetLine.objects.create(project=self.project, label="Paint", estimated=Decimal("300"))

    def test_link_reassign_and_unlink(self):
        purchase = self.txn("-45.00")
        url = reverse("household:project_spending", args=[self.project.pk])

        self.client.post(url, {"transaction": purchase.pk, "budget_line": self.line.pk})
        expense = ProjectExpense.objects.get()
        self.assertEqual(expense.budget_line, self.line)

        self.client.post(reverse("household:expense_edit", args=[self.project.pk, expense.pk]), {"budget_line": ""})
        expense.refresh_from_db()
        self.assertIsNone(expense.budget_line)

        self.client.post(reverse("household:expense_delete", args=[self.project.pk, expense.pk]))
        self.assertFalse(ProjectExpense.objects.exists())

    def test_removing_a_line_keeps_its_spending_on_the_project(self):
        spending.link_expense(self.project, self.txn("-45.00").pk, self.line.pk)

        self.client.post(reverse("household:budget_line_delete", args=[self.project.pk, self.line.pk]))

        self.assertEqual(spending.budget_summary(self.project).unassigned, Decimal("45.00"))

    def test_the_project_page_shows_spent_of_budget(self):
        self.project.budget_total = Decimal("1000")
        self.project.save()
        spending.link_expense(self.project, self.txn("-412.87").pk, self.line.pk)

        response = self.client.get(reverse("household:project_detail", args=[self.project.pk]))

        self.assertContains(response, "$412.87")
        self.assertContains(response, "$587.13 left")

    def test_the_search_term_survives_the_redirect_safely(self):
        purchase = self.txn("-45.00", merchant="Tile & Stone")
        url = reverse("household:project_spending", args=[self.project.pk])

        response = self.client.post(url, {"transaction": purchase.pk, "q": "Tile & Stone"})

        self.assertRedirects(response, f"{url}?q=Tile+%26+Stone")


class JobLinkTests(SpendingTestCase):
    def setUp(self):
        super().setUp()
        sign_in(self.client, self.david)
        chore = Chore.objects.create(title="Replace the furnace filter", frequency=Frequency.DAILY, interval=90,
                                     anchor=Anchor.AFTER_COMPLETION, starts_on=household_today())
        self.item = MaintenanceItem.objects.create(chore=chore, estimated_cost=Decimal("25.00"))
        occurrences.reschedule(chore)
        self.job = chore.occurrences.get(status=OccurrenceStatus.OPEN)
        occurrences.complete(self.job, by=self.david, cost=Decimal("25.00"))
        self.job.refresh_from_db()
        self.url = reverse("household:job_link", args=[self.item.pk, self.job.pk])

    def test_linking_takes_the_cost_from_the_purchase(self):
        purchase = self.txn("-27.49", slug="housing-maintenance", days_ago=1)

        self.client.post(self.url, {"transaction": purchase.pk})

        self.job.refresh_from_db()
        self.assertEqual((self.job.transaction, self.job.cost), (purchase, Decimal("27.49")))

    def test_a_refund_leaves_the_cost_alone_and_unlinking_keeps_it(self):
        spending.link_job(self.job, self.txn("5.00", slug="housing-maintenance").pk)
        self.job.refresh_from_db()
        self.assertEqual(self.job.cost, Decimal("25.00"))

        self.client.post(self.url, {"unlink": "1"})
        self.job.refresh_from_db()
        self.assertIsNone(self.job.transaction)
        self.assertEqual(self.job.cost, Decimal("25.00"))

    def test_only_a_done_job_of_this_item_can_be_linked(self):
        open_one = self.item.chore.occurrences.get(status=OccurrenceStatus.OPEN)
        other_item = MaintenanceItem.objects.create(chore=Chore.objects.create(title="Other"))

        self.assertEqual(self.client.get(reverse("household:job_link", args=[self.item.pk, open_one.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("household:job_link", args=[other_item.pk, self.job.pk])).status_code, 404)

    def test_suggestions_are_near_the_day_it_was_done(self):
        self.txn("-27.49", slug="housing-maintenance", merchant="Near", days_ago=3)
        self.txn("-27.49", slug="housing-maintenance", merchant="Far", days_ago=40)

        response = self.client.get(self.url)

        self.assertEqual([txn.merchant for txn in response.context["candidates"]], ["Near"])


class ProjectedCostTests(TestCase):
    def setUp(self):
        self.david = make_member("david")

    def item(self, cost, **chore_fields):
        chore = Chore.objects.create(title="x", **chore_fields)
        item = MaintenanceItem.objects.create(chore=chore, estimated_cost=Decimal(cost) if cost else None)
        occurrences.reschedule(chore, today=TODAY)
        return item

    def project(self, days):
        items = maintenance.items_with_state(TODAY)
        return spending.projected_costs(items, TODAY, days)

    def test_fixed_after_completion_paused_and_uncosted(self):
        self.item("100.00", frequency=Frequency.YEARLY, starts_on=date(2026, 10, 15))  # once a year
        self.item("25.00", frequency=Frequency.DAILY, interval=90, anchor=Anchor.AFTER_COMPLETION,
                  starts_on=TODAY - timedelta(days=12))  # overdue now, then every 90 days
        self.item(None, frequency=Frequency.MONTHLY, starts_on=TODAY)  # no usual cost: left out
        paused = self.item("999.00", frequency=Frequency.MONTHLY, starts_on=TODAY)
        paused.chore.is_active = False
        paused.chore.save()
        occurrences.reschedule(paused.chore, today=TODAY)

        ninety = self.project(90)
        year = self.project(365)

        # 90 days: the yearly one once; the filter now and again on Dec 29.
        self.assertEqual(ninety["total"], Decimal("150.00"))
        # 12 months: yearly once (next Oct 15 is day 380); filter now + 4 more.
        self.assertEqual(year["total"], Decimal("225.00"))
        # Biggest expected cost first: the filter (5 × $25) before the yearly job.
        self.assertEqual([p.total for p in year["items"]], [Decimal("125.00"), Decimal("100.00")])

    def test_the_upkeep_page_shows_both_horizons(self):
        sign_in(self.client, self.david)
        self.item("100.00", frequency=Frequency.YEARLY, starts_on=household_today() + timedelta(days=10))

        response = self.client.get(reverse("household:upkeep"))

        self.assertContains(response, "Next 90 days")
        self.assertContains(response, "Next 12 months")
        self.assertContains(response, "$100")


class ReviewFindingTests(SpendingTestCase):
    def setUp(self):
        super().setUp()
        sign_in(self.client, self.david)
        self.project = Project.objects.create(name="Kitchen", status=ProjectStatus.ACTIVE)

    def test_only_spending_can_be_linked(self):
        """Found in review: a posted transfer or paycheck id was accepted."""
        transfer = self.txn("-500.00", is_transfer=True)
        paycheck = self.txn("3150.00", slug="income-salary")

        self.assertIsNone(spending.link_expense(self.project, transfer.pk))
        self.assertIsNone(spending.link_expense(self.project, paycheck.pk))
        self.assertFalse(ProjectExpense.objects.exists())

    def test_non_numeric_ids_are_not_found_rather_than_a_500(self):
        purchase = self.txn("-45.00")
        url = reverse("household:project_spending", args=[self.project.pk])

        response = self.client.post(url, {"transaction": purchase.pk, "budget_line": "abc"})
        self.assertEqual(response.status_code, 302)
        expense = ProjectExpense.objects.get()
        self.assertIsNone(expense.budget_line)

        response = self.client.post(
            reverse("household:expense_edit", args=[self.project.pk, expense.pk]), {"budget_line": "abc"}
        )
        self.assertEqual(response.status_code, 302)

    def test_undo_forgets_the_purchase_link_too(self):
        chore = Chore.objects.create(title="Filter", frequency=Frequency.DAILY, interval=90,
                                     anchor=Anchor.AFTER_COMPLETION, starts_on=household_today())
        MaintenanceItem.objects.create(chore=chore)
        occurrences.reschedule(chore)
        job = chore.occurrences.get(status=OccurrenceStatus.OPEN)
        occurrences.complete(job, by=self.david)
        job.refresh_from_db()
        spending.link_job(job, self.txn("-27.49", slug="housing-maintenance").pk)

        occurrences.reopen(job)

        job.refresh_from_db()
        self.assertIsNone(job.transaction)
        self.assertIsNone(job.cost)


class ProjectionCountTests(TestCase):
    def test_an_after_completion_count_limit_caps_the_projection(self):
        """Found in review: "3 times" was projected every 90 days forever."""
        chore = Chore.objects.create(title="x", frequency=Frequency.DAILY, interval=30,
                                     anchor=Anchor.AFTER_COMPLETION, starts_on=TODAY, max_occurrences=3)
        MaintenanceItem.objects.create(chore=chore, estimated_cost=Decimal("10.00"))
        occurrences.reschedule(chore, today=TODAY)

        projection = spending.projected_costs(maintenance.items_with_state(TODAY), TODAY, 365)

        # The open one plus the two the count still allows — not 12.
        self.assertEqual(projection["total"], Decimal("30.00"))


class RoundOneMoneyTests(SpendingTestCase):
    def setUp(self):
        super().setUp()
        sign_in(self.client, self.david)
        self.project = Project.objects.create(name="Kitchen", status=ProjectStatus.ACTIVE, budget_total=Decimal("1000.00"))

    def page(self):
        return self.client.get(reverse("household:project_detail", args=[self.project.pk])).content.decode()

    def test_cents_are_shown_so_over_and_left_are_never_wrong(self):
        spending.link_expense(self.project, self.txn("-1000.40").pk)

        body = self.page()

        self.assertIn("$1,000.40", body)
        self.assertIn("$0.40 over", body)

    def test_a_refund_only_project_reads_sensibly(self):
        spending.link_expense(self.project, self.txn("25.00").pk)

        summary = spending.budget_summary(self.project)

        self.assertEqual(summary.percent, 0)
        body = self.page()
        self.assertIn("-$25.00", body)
        self.assertNotIn("$-", body)  # round 2: the header still read "$-25"

    def test_a_purchase_finance_later_calls_a_transfer_stops_counting(self):
        purchase = self.txn("-300.00")
        spending.link_expense(self.project, purchase.pk)
        purchase.is_transfer = True
        purchase.save()

        summary = spending.budget_summary(self.project)

        self.assertEqual(summary.actual, Decimal("0"))
        self.assertFalse(summary.expenses[0].counts)
        self.assertIn("Not counted", self.page())


class JobExclusivityTests(SpendingTestCase):
    def setUp(self):
        super().setUp()
        self.jobs = []
        for title in ("Filter", "Gutters"):
            chore = Chore.objects.create(title=title, frequency=Frequency.DAILY, interval=90,
                                         anchor=Anchor.AFTER_COMPLETION, starts_on=household_today())
            MaintenanceItem.objects.create(chore=chore)
            occurrences.reschedule(chore)
            job = chore.occurrences.get(status=OccurrenceStatus.OPEN)
            occurrences.complete(job, by=self.david)
            job.refresh_from_db()
            self.jobs.append(job)

    def test_one_purchase_backs_one_job(self):
        purchase = self.txn("-400.00", slug="housing-maintenance")

        self.assertTrue(spending.link_job(self.jobs[0], purchase.pk))
        self.assertFalse(spending.link_job(self.jobs[1], purchase.pk))
        self.assertNotIn(purchase.pk, [t.pk for t in spending.job_candidates(self.jobs[1], household_today())])

    def test_the_database_holds_the_line_too(self):
        from django.db import IntegrityError, transaction

        purchase = self.txn("-400.00", slug="housing-maintenance")
        spending.link_job(self.jobs[0], purchase.pk)
        self.jobs[1].transaction = purchase
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.jobs[1].save()

    def test_a_refund_cannot_be_a_jobs_purchase(self):
        refund = self.txn("5.00", slug="housing-maintenance")

        self.assertFalse(spending.link_job(self.jobs[0], refund.pk))
        self.assertNotIn(refund.pk, [t.pk for t in spending.job_candidates(self.jobs[0], household_today())])
