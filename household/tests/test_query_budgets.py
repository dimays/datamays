"""Ceilings on how many queries each household page may run.

The same idea as finance's test_query_budgets.py: the ceilings are loose on
purpose — they exist to catch a new N+1, not to freeze today's numbers.
Raising one by a few because a page genuinely does more is fine; raising one
because the household added chores is the signal this file is here to give.
The feature test files also assert the stronger property directly: each
page's count stays *flat* as chores, items, and projects are added.

The dataset is a realistic household's worth — enough rows that a per-row
query would blow straight through a ceiling.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from finance.tests.factories import make_account, make_transaction
from household.dates import household_today
from household.models import BudgetLine, Chore, MaintenanceItem, Milestone, Project, ProjectStatus
from household.scheduling import Anchor, Frequency
from household.services import occurrences, spending

from .factories import make_chore, make_member, sign_in

# Roughly double what each page ran over this dataset when the ceilings were
# set (today 13, chores 9, chore_list 8, upkeep 9, upkeep_detail 9, projects
# 7, project_detail 13) — room for real features, none for a per-row query.
CEILINGS = {
    "today": 26,
    "chores": 18,
    "chore_list": 16,
    "upkeep": 18,
    "upkeep_detail": 18,
    "projects": 14,
    "project_detail": 26,
}


class QueryBudgetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_finance_categories", verbosity=0)
        today = household_today()
        cls.david = make_member("david", first_name="David")
        cls.maddie = make_member("maddie", first_name="Maddie")

        for index in range(12):
            owner = (cls.david, cls.maddie, None)[index % 3]
            make_chore(owner, title=f"Chore {index}", frequency=Frequency.WEEKLY,
                       starts_on=today - timedelta(days=index))

        for index in range(8):
            chore = Chore.objects.create(title=f"Upkeep {index}", frequency=Frequency.DAILY, interval=90,
                                         anchor=Anchor.AFTER_COMPLETION, starts_on=today - timedelta(days=index))
            item = MaintenanceItem.objects.create(chore=chore, estimated_cost=Decimal("25"))
            occurrences.reschedule(chore)
            occurrences.complete(chore.occurrences.get(status="open"), by=cls.david, cost=Decimal("20"))
        cls.item = item

        account = make_account()
        for index in range(4):
            project = Project.objects.create(name=f"Project {index}", status=ProjectStatus.ACTIVE,
                                             start_on=today - timedelta(days=30), budget_total=Decimal("1000"))
            line = BudgetLine.objects.create(project=project, label="Line", estimated=Decimal("500"))
            for step in range(4):
                milestone = Milestone.objects.create(project=project, name=f"M{step}",
                                                     target_on=today + timedelta(days=step * 7))
                task = Chore.objects.create(title=f"Task {index}.{step}", project=project, milestone=milestone,
                                            assignee=cls.david, starts_on=today + timedelta(days=step))
                occurrences.reschedule(task)
                purchase = make_transaction(account, amount=Decimal("-12.50"), posted_on=today,
                                            description_raw=f"STORE {index}.{step}")
                spending.link_expense(project, purchase.pk, line.pk)
        cls.project = project

    def setUp(self):
        sign_in(self.client, self.david)

    def urls(self):
        return {
            "today": reverse("household:today"),
            "chores": reverse("household:chores"),
            "chore_list": reverse("household:chore_list"),
            "upkeep": reverse("household:upkeep"),
            "upkeep_detail": reverse("household:upkeep_detail", args=[self.item.pk]),
            "projects": reverse("household:projects"),
            "project_detail": reverse("household:project_detail", args=[self.project.pk]),
        }

    def test_every_page_stays_under_its_ceiling(self):
        for name, url in self.urls().items():
            self.client.get(url)  # first visit creates preference rows
            with self.subTest(page=name):
                with CaptureQueriesContext(connection) as queries:
                    response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertLessEqual(len(queries), CEILINGS[name], f"{name}: {len(queries)} queries")
