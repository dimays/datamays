"""The household shell: sections, the Today screen, and the member group."""

from decimal import Decimal
from importlib import import_module

from django.apps import apps
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from datamays.settings import _scrub_finance_data
from finance.models import Budget, BudgetPeriod, UserPreference
from finance.periods import monthly_period
from household.access import HOUSEHOLD_GROUP, is_household_member
from household.dates import household_today

from .factories import make_member, sign_in

rename_group = import_module("household.migrations.0001_rename_member_group")


def sections_in(body, label):
    start = body.index(f'aria-label="{label}"')
    return body[start:body.index("</nav>", start)]


class SectionNavTests(TestCase):
    def setUp(self):
        sign_in(self.client, make_member("david", first_name="David"))

    def test_the_header_and_tab_bar_list_the_same_sections(self):
        body = self.client.get(reverse("household:today")).content.decode()

        for label in ("Sections", "Primary"):
            with self.subTest(surface=label):
                nav = sections_in(body, label)
                self.assertIn(f'href="{reverse("household:today")}"', nav)
                self.assertIn(f'href="{reverse("finance:home")}"', nav)

    def test_the_current_section_is_marked(self):
        cases = [
            (reverse("household:today"), "Today"),
            (reverse("finance:home"), "Finance"),
            (reverse("finance:rules"), "Finance"),
        ]

        for url, expected in cases:
            with self.subTest(url=url):
                sections = self.client.get(url).context["sections"]
                active = [section["label"] for section in sections if section["is_active"]]
                self.assertEqual(active, [expected])

    def test_every_page_carries_the_household_name(self):
        for url, title in [
            (reverse("household:today"), "Today — Mays Household"),
            (reverse("finance:home"), "Home — Mays Household"),
        ]:
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), f"<title>{title}</title>")


class TodayTests(TestCase):
    def setUp(self):
        self.user = make_member("david", first_name="David")
        sign_in(self.client, self.user)

    def make_period(self, name, actual, target="800.00"):
        start, end = monthly_period(household_today().replace(day=1), household_today())
        budget = Budget.objects.create(name=name, amount=Decimal(target))
        BudgetPeriod.objects.create(
            budget=budget,
            period_start=start,
            period_end=end,
            target_amount=Decimal(target),
            actual_amount=Decimal(actual),
        )
        return budget

    def test_it_is_where_sign_in_lands(self):
        from django.conf import settings

        self.assertEqual(reverse(settings.LOGIN_REDIRECT_URL), reverse("household:today"))

    def test_it_greets_by_name_with_the_household_date(self):
        response = self.client.get(reverse("household:today"))

        self.assertContains(response, "Hi, David")
        self.assertContains(response, household_today().strftime("%A, %B"))

    def test_it_shows_finances_own_budget_widget(self):
        self.make_period("Groceries", "300.00")
        self.make_period("Eating out", "400.00", target="300.00")

        response = self.client.get(reverse("household:today"))

        self.assertTemplateUsed(response, "finance/widgets/budgets.html")
        self.assertContains(response, "Groceries")
        # Worst pace first, exactly as on the finance homepage.
        body = response.content.decode()
        self.assertLess(body.index("Eating out"), body.index("Groceries"))
        self.assertContains(response, "$100 over")

    def test_it_honors_the_budget_selection_in_finance_preferences(self):
        shown = self.make_period("Groceries", "300.00")
        self.make_period("Hidden", "50.00")
        preference = UserPreference.for_user(self.user)
        preference.homepage_budget_ids = [shown.pk]
        preference.save()

        response = self.client.get(reverse("household:today"))

        self.assertContains(response, "Groceries")
        self.assertNotContains(response, "Hidden")

    def test_no_budgets_is_an_invitation_not_an_error(self):
        response = self.client.get(reverse("household:today"))

        self.assertContains(response, "No budgets running.")


class MemberGroupMigrationTests(TestCase):
    """The rename that carries both people across on deploy."""

    def setUp(self):
        Group.objects.filter(name=HOUSEHOLD_GROUP).delete()

    def test_members_of_the_old_group_can_still_get_in(self):
        user = make_member("david", in_group=False)
        user.groups.add(Group.objects.create(name="finance"))

        rename_group.forwards(apps, None)

        self.assertTrue(is_household_member(user))
        self.assertFalse(Group.objects.filter(name="finance").exists())

    def test_an_existing_household_group_is_merged_into(self):
        david = make_member("david", in_group=False)
        maddie = make_member("maddie", in_group=False)
        david.groups.add(Group.objects.create(name="finance"))
        maddie.groups.add(Group.objects.create(name=HOUSEHOLD_GROUP))

        rename_group.forwards(apps, None)

        self.assertTrue(is_household_member(david))
        self.assertTrue(is_household_member(maddie))
        self.assertFalse(Group.objects.filter(name="finance").exists())

    def test_it_reverses_cleanly_and_is_harmless_on_an_empty_database(self):
        user = make_member("david", in_group=False)
        user.groups.add(Group.objects.create(name=HOUSEHOLD_GROUP))

        rename_group.backwards(apps, None)
        self.assertTrue(user.groups.filter(name="finance").exists())

        Group.objects.all().delete()
        rename_group.forwards(apps, None)
        self.assertFalse(Group.objects.exists())


class PrivacyTests(TestCase):
    def test_household_errors_reach_sentry_without_request_data(self):
        event = {
            "request": {"url": "https://datamays.com/household/", "data": "private"},
            "user": {"username": "david"},
        }

        scrubbed = _scrub_finance_data(event, {})

        self.assertNotIn("request", scrubbed)
        self.assertNotIn("user", scrubbed)


class HelpTests(TestCase):
    def test_every_section_is_explained_and_finance_help_is_linked(self):
        sign_in(self.client, make_member("david"))

        response = self.client.get(reverse("household:help"))

        for heading in ["Today", "Chores", "How chores repeat", "Upkeep", "Projects", "Morning digest"]:
            with self.subTest(heading=heading):
                self.assertContains(response, f'<h2 class="font-semibold">{heading}</h2>', html=False)
        self.assertContains(response, reverse("finance:help"))
