"""The Chores screens: the form, the checklist, one-tap actions, Today."""

from datetime import date, timedelta
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from household.dates import household_today
from household.models import Chore, HouseholdPreference, OccurrenceStatus
from household.scheduling import Anchor, Frequency
from household.services import checklist, occurrences

from .factories import make_chore, make_member, sign_in

HTMX = {"HTTP_HX_REQUEST": "true", "HTTP_HX_CURRENT_URL": "http://testserver/household/chores/"}


def form_data(**overrides):
    data = {
        "title": "Vacuum the living room",
        "whose": "personal",
        "frequency": Frequency.ONCE,
        "starts_on": "",
        "interval": 1,
        "monthly_mode": "day",
        "anchor": Anchor.FIXED,
        "is_active": "on",
        "notes": "",
    }
    data.update(overrides)
    return data


class ChoreFormTests(TestCase):
    def setUp(self):
        self.david = make_member("david", first_name="David")
        self.maddie = make_member("maddie", first_name="Maddie")
        sign_in(self.client, self.david)

    def test_a_personal_weekly_chore_is_created_and_opened(self):
        today = household_today()
        response = self.client.post(
            reverse("household:chore_create"),
            form_data(frequency=Frequency.WEEKLY, starts_on=today.isoformat(), weekdays=["5", "6"]),
        )

        chore = Chore.objects.get()
        self.assertRedirects(response, reverse("household:chore_detail", args=[chore.pk]))
        self.assertEqual((chore.owner, chore.assignee), (self.david, self.david))
        self.assertEqual(chore.weekdays, [5, 6])
        self.assertEqual(chore.occurrences.filter(status=OccurrenceStatus.OPEN).count(), 1)

    def test_a_shared_chore_has_no_owner_and_an_optional_assignee(self):
        self.client.post(
            reverse("household:chore_create"),
            form_data(title="Clean the gutters", whose="household", assignee=self.maddie.pk,
                      others_can_manage="on"),
        )

        chore = Chore.objects.get()
        self.assertIsNone(chore.owner)
        self.assertEqual(chore.assignee, self.maddie)
        self.assertFalse(chore.others_can_manage)

    def test_hidden_fields_left_behind_do_not_block_saving(self):
        """Weekdays ticked, then switched to monthly: the weekdays are dropped
        rather than failing validation for a field the form no longer shows."""
        response = self.client.post(
            reverse("household:chore_create"),
            form_data(frequency=Frequency.MONTHLY, starts_on="2026-10-14", weekdays=["0"],
                      deadline="2026-10-20"),
        )

        chore = Chore.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual((chore.weekdays, chore.deadline), ([], None))

    def test_schedule_errors_come_back_on_their_fields(self):
        response = self.client.post(
            reverse("household:chore_create"),
            form_data(frequency=Frequency.YEARLY, starts_on="2027-01-15",
                      season_start_month=4, season_end_month=10),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("season_start_month", response.context["form"].errors)
        self.assertFalse(Chore.objects.exists())

    def test_the_default_sharing_comes_from_preferences(self):
        preference = HouseholdPreference.for_user(self.david)
        preference.share_new_chores = True
        preference.save()

        response = self.client.get(reverse("household:chore_create"))

        self.assertTrue(response.context["form"].initial["others_can_manage"])

    def test_editing_the_title_does_not_reset_an_overdue_chore(self):
        chore = make_chore(self.david, frequency=Frequency.WEEKLY, starts_on=date(2026, 9, 7),
                           today=date(2026, 9, 7))
        overdue = chore.occurrences.get(status=OccurrenceStatus.OPEN)

        self.client.post(
            reverse("household:chore_edit", args=[chore.pk]),
            form_data(title="Bins and recycling", frequency=Frequency.WEEKLY, starts_on="2026-09-07"),
        )

        self.assertEqual(chore.occurrences.get(status=OccurrenceStatus.OPEN).pk, overdue.pk)

    def test_editing_the_schedule_replaces_the_open_occurrence(self):
        chore = make_chore(self.david, frequency=Frequency.WEEKLY, starts_on=date(2026, 9, 7),
                           today=date(2026, 9, 7))
        old = chore.occurrences.get(status=OccurrenceStatus.OPEN)

        self.client.post(
            reverse("household:chore_edit", args=[chore.pk]),
            form_data(title=chore.title, frequency=Frequency.WEEKLY, starts_on="2026-09-08"),
        )

        self.assertNotEqual(chore.occurrences.get(status=OccurrenceStatus.OPEN).pk, old.pk)

    def test_pausing_from_the_form_takes_it_off_the_list(self):
        chore = make_chore(self.david, frequency=Frequency.DAILY, starts_on=household_today())

        data = form_data(title=chore.title, frequency=Frequency.DAILY, starts_on=household_today().isoformat())
        del data["is_active"]
        self.client.post(reverse("household:chore_edit", args=[chore.pk]), data)

        self.assertFalse(chore.occurrences.filter(status=OccurrenceStatus.OPEN).exists())
        self.assertContains(self.client.get(reverse("household:chore_list")), "paused")

    def test_the_live_preview(self):
        response = self.client.get(
            reverse("household:chore_preview"),
            form_data(title="", frequency=Frequency.WEEKLY, starts_on="2026-10-05", weekdays=["0", "3"]),
        )

        self.assertContains(response, "Weekly on Mon, Thu")

    def test_the_preview_shows_schedule_errors_but_not_a_missing_title(self):
        response = self.client.get(
            reverse("household:chore_preview"),
            form_data(title="", frequency=Frequency.MONTHLY, starts_on="2026-10-09", monthly_mode="last_weekday"),
        )

        self.assertContains(response, "the last Friday of October")
        self.assertNotContains(response, "This field is required")


class ActionTests(TestCase):
    def setUp(self):
        self.david = make_member("david", first_name="David")
        self.maddie = make_member("maddie", first_name="Maddie")
        sign_in(self.client, self.david)
        self.chore = make_chore(self.david, frequency=Frequency.DAILY, starts_on=household_today())
        self.current = self.chore.occurrences.get(status=OccurrenceStatus.OPEN)

    def url(self, action, occurrence=None):
        return reverse("household:occurrence_action", args=[(occurrence or self.current).pk, action])

    def test_htmx_done_swaps_in_the_result_with_undo(self):
        response = self.client.post(self.url("complete"), **HTMX)

        self.assertTemplateUsed(response, "household/chores/_row_closed.html")
        self.assertContains(response, "Next: Tomorrow")
        self.assertContains(response, "Undo")
        # The swapped-in row's fallback returns to the page, not the endpoint.
        self.assertContains(response, 'name="next" value="/household/chores/"')

    def test_htmx_undo_swaps_the_row_back(self):
        self.client.post(self.url("complete"), **HTMX)

        response = self.client.post(self.url("undo"), **HTMX)

        self.assertTemplateUsed(response, "household/chores/_row.html")
        self.current.refresh_from_db()
        self.assertTrue(self.current.is_open)

    def test_without_javascript_it_redirects_back(self):
        response = self.client.post(self.url("complete"), {"next": "/household/"})

        self.assertRedirects(response, "/household/")

    def test_a_hostile_next_is_ignored(self):
        response = self.client.post(self.url("complete"), {"next": "https://evil.example.com/"})

        self.assertRedirects(response, reverse("household:chores"))

    def test_doing_the_other_persons_chore_records_who_did_it(self):
        hers = make_chore(self.maddie, title="Walk the dog", frequency=Frequency.DAILY, starts_on=household_today())
        current = hers.occurrences.get(status=OccurrenceStatus.OPEN)

        response = self.client.post(self.url("complete", current), **HTMX)

        current.refresh_from_db()
        self.assertEqual(current.completed_by, self.david)
        self.assertEqual(response.status_code, 200)


class ChecklistTests(TestCase):
    def setUp(self):
        self.david = make_member("david", first_name="David")
        self.maddie = make_member("maddie", first_name="Maddie")
        sign_in(self.client, self.david)

    def test_yours_shared_and_theirs_behind_the_toggle(self):
        make_chore(self.david, title="Mine")
        make_chore(None, title="Ours")
        make_chore(self.maddie, title="Hers")

        hidden = self.client.get(reverse("household:chores"))
        self.assertContains(hidden, "Mine")
        self.assertContains(hidden, "Ours")
        self.assertNotContains(hidden, "Hers")

        self.client.post(reverse("household:chores_partner_toggle"))
        shown = self.client.get(reverse("household:chores"))
        self.assertContains(shown, "Hers")
        self.assertContains(shown, "Maddie’s")

    def test_buckets(self):
        today = date(2026, 9, 30)
        rows = {
            name: checklist.bucket_for(
                make_chore(self.david, title=name, today=today, **fields)
                .occurrences.get(status=OccurrenceStatus.OPEN),
                today,
            )
            for name, fields in {
                "late": {"starts_on": date(2026, 9, 29)},
                "due now, deadline ahead": {"starts_on": date(2026, 9, 29), "deadline": date(2026, 10, 2)},
                "today": {"starts_on": today},
                "in a week": {"starts_on": date(2026, 10, 7)},
                "in eight days": {"starts_on": date(2026, 10, 8)},
                "whenever": {"starts_on": None},
            }.items()
        }

        self.assertEqual(rows, {
            "late": "overdue",
            "due now, deadline ahead": "today",
            "today": "today",
            "in a week": "upcoming",
            "in eight days": "later",
            "whenever": "whenever",
        })

    def test_the_query_count_does_not_grow_with_chores(self):
        def count():
            with CaptureQueriesContext(connection) as queries:
                self.client.get(reverse("household:chores"))
            return len(queries)

        count()  # first visit creates this person's preference rows
        for index in range(3):
            make_chore(self.david, title=f"Chore {index}", frequency=Frequency.DAILY, starts_on=household_today())
        few = count()
        for index in range(3, 20):
            make_chore(self.david, title=f"Chore {index}", frequency=Frequency.DAILY, starts_on=household_today())

        self.assertEqual(count(), few)


class TodayTests(TestCase):
    def setUp(self):
        self.david = make_member("david", first_name="David")
        self.maddie = make_member("maddie", first_name="Maddie")
        sign_in(self.client, self.david)
        self.today = household_today()

    def summary(self, include_partner=False):
        return checklist.today_summary(self.david, include_partner=include_partner, today=self.today)

    def titles(self, rows):
        return [row.chore.title for row in rows]

    def test_overdue_is_yours_and_shared_most_late_first(self):
        make_chore(self.david, title="A little late", starts_on=self.today - timedelta(days=1))
        make_chore(None, title="Very late", starts_on=self.today - timedelta(days=9))
        make_chore(self.maddie, title="Hers, late", starts_on=self.today - timedelta(days=3))

        self.assertEqual(self.titles(self.summary()["overdue"]), ["Very late", "A little late"])

    def test_coming_up_is_only_the_easy_to_forget_kind(self):
        soon = self.today + timedelta(days=3)
        make_chore(self.david, title="One-off", starts_on=soon)
        make_chore(None, title="Quarterly", frequency=Frequency.MONTHLY, interval=3, starts_on=soon)
        make_chore(self.david, title="Filter", frequency=Frequency.DAILY, interval=90,
                   anchor=Anchor.AFTER_COMPLETION, starts_on=soon)
        make_chore(self.david, title="Weekly routine", frequency=Frequency.WEEKLY, starts_on=soon)
        make_chore(self.david, title="Every other week", frequency=Frequency.WEEKLY, interval=2, starts_on=soon)
        make_chore(self.david, title="Next month", starts_on=self.today + timedelta(days=30))

        self.assertEqual(
            sorted(self.titles(self.summary()["coming_up"])),
            ["Every other week", "Filter", "One-off", "Quarterly"],
        )

    def test_the_partners_overdue_and_today_behind_the_toggle(self):
        make_chore(self.maddie, title="Hers today", starts_on=self.today)
        make_chore(self.maddie, title="Hers later", starts_on=self.today + timedelta(days=3))

        self.assertEqual(self.summary()["partner_rows"], [])
        self.assertEqual(self.titles(self.summary(include_partner=True)["partner_rows"]), ["Hers today"])

    def test_the_page_puts_overdue_first_and_the_budget_widget_last(self):
        make_chore(self.david, title="Late thing", starts_on=self.today - timedelta(days=2))

        body = self.client.get(reverse("household:today")).content.decode()

        self.assertLess(body.index("Late thing"), body.index("Budget"))
        self.assertIn("2 days overdue", body)

    def test_the_nav_badge_counts_yours_and_shared_overdue(self):
        make_chore(self.david, title="Mine", starts_on=self.today - timedelta(days=1))
        make_chore(None, title="Ours", starts_on=self.today - timedelta(days=1))
        make_chore(self.maddie, title="Hers", starts_on=self.today - timedelta(days=1))
        make_chore(self.david, title="Not late yet", starts_on=self.today - timedelta(days=1),
                   deadline=self.today + timedelta(days=1))

        self.assertEqual(checklist.overdue_count(self.david, self.today), 2)
        sections = self.client.get(reverse("finance:home")).context["sections"]
        chores = next(section for section in sections if section["label"] == "Chores")
        self.assertEqual(chores["badge_count"], 2)

    def test_the_query_count_does_not_grow_with_chores(self):
        def count():
            with CaptureQueriesContext(connection) as queries:
                self.client.get(reverse("household:today"))
            return len(queries)

        count()  # first visit creates this person's preference rows
        make_chore(self.david, title="One", starts_on=self.today)
        few = count()
        for index in range(15):
            make_chore(None, title=f"Shared {index}", starts_on=self.today - timedelta(days=1))

        self.assertEqual(count(), few)


class CollapseOnReadTests(TestCase):
    def test_the_checklist_rolls_a_stale_fixed_chore_forward(self):
        david = make_member("david")
        sign_in(self.client, david)
        chore = make_chore(david, frequency=Frequency.WEEKLY, starts_on=date(2026, 10, 5), today=date(2026, 10, 1))

        with patch("household.services.checklist.household_today", return_value=date(2026, 10, 20)):
            self.client.get(reverse("household:chores"))

        self.assertEqual(
            list(chore.occurrences.values_list("status", flat=True)),
            [OccurrenceStatus.MISSED, OccurrenceStatus.OPEN],
        )


class PreferencesTests(TestCase):
    def test_the_sharing_default_can_be_set(self):
        david = make_member("david")
        sign_in(self.client, david)

        response = self.client.post(reverse("household:preferences"), {"share_new_chores": "on"})

        self.assertRedirects(response, reverse("household:preferences"))
        self.assertTrue(HouseholdPreference.for_user(david).share_new_chores)
        self.assertFalse(HouseholdPreference.for_user(david).show_partner_chores)
