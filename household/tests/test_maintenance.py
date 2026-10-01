"""Maintenance: items, the starter list, the cost log, and the Upkeep pages."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from household.dates import household_timezone, household_today
from household.maintenance_library import LIBRARY
from household.models import Chore, MaintenanceItem, Occurrence, OccurrenceStatus
from household.scheduling import Anchor, Frequency
from household.services import maintenance, occurrences

from .factories import make_member, sign_in

TODAY = date(2026, 9, 30)


def at(day, hour=10):
    return datetime.combine(day, time(hour), tzinfo=household_timezone())


def make_item(title="Replace the furnace filter", *, today=TODAY, **chore_fields):
    chore_fields.setdefault("frequency", Frequency.YEARLY)
    chore_fields.setdefault("starts_on", today)
    chore = Chore.objects.create(title=title, owner=None, **chore_fields)
    item = MaintenanceItem.objects.create(chore=chore, estimated_cost=Decimal("25.00"))
    occurrences.reschedule(chore, today=today)
    return item


def form_data(**overrides):
    data = {
        "chore-title": "Clean the dryer vent",
        "chore-frequency": Frequency.YEARLY,
        "chore-starts_on": "2027-03-01",
        "chore-interval": 1,
        "chore-monthly_mode": "day",
        "chore-anchor": Anchor.FIXED,
        "chore-is_active": "on",
        "chore-notes": "",
        "item-area": "appliances",
        "item-location": "Laundry room",
        "item-instructions": "",
        "item-supplies": "",
        "item-supply_url": "",
        "item-estimated_cost": "",
    }
    data.update(overrides)
    return data


class LibraryTests(TestCase):
    def test_every_entry_is_a_valid_schedule(self):
        for entry in LIBRARY:
            with self.subTest(entry=entry.key):
                item = maintenance.adopt(entry.key, today=TODAY)
                item.chore.full_clean()
                self.assertIsNone(item.chore.owner)
                self.assertTrue(item.chore.occurrences.filter(status=OccurrenceStatus.OPEN).exists())

    def test_dates_resolve_to_the_soonest_in_the_cycle(self):
        water_off = maintenance.adopt("outdoor-water-off", today=TODAY)  # Oct 15 yearly
        water_on = maintenance.adopt("outdoor-water-on", today=TODAY)  # Apr 15 yearly
        gutters = maintenance.adopt("gutters", today=TODAY)  # every 6 months from Apr 30
        filter_ = maintenance.adopt("furnace-filter", today=TODAY)  # after completion

        self.assertEqual(water_off.chore.starts_on, date(2026, 10, 15))
        self.assertEqual(water_on.chore.starts_on, date(2027, 4, 15))
        self.assertEqual(gutters.chore.starts_on, date(2026, 10, 30))
        self.assertEqual(filter_.chore.starts_on, TODAY)

    def test_the_list_hides_what_is_already_adopted_and_refuses_a_repeat(self):
        sign_in(self.client, make_member("david"))
        before = len(maintenance.available_library_entries())

        self.client.post(reverse("household:upkeep_adopt", args=["gutters"]))
        self.client.post(reverse("household:upkeep_adopt", args=["gutters"]))

        self.assertEqual(MaintenanceItem.objects.count(), 1)
        self.assertEqual(len(maintenance.available_library_entries()), before - 1)

    def test_an_unknown_key_is_a_404(self):
        sign_in(self.client, make_member("david"))
        self.assertEqual(self.client.post(reverse("household:upkeep_adopt", args=["nope"])).status_code, 404)


class FormTests(TestCase):
    def setUp(self):
        self.david = make_member("david", first_name="David")
        sign_in(self.client, self.david)

    def test_creating_an_item_creates_its_shared_chore(self):
        response = self.client.post(reverse("household:upkeep_create"), form_data())

        item = MaintenanceItem.objects.get()
        self.assertRedirects(response, reverse("household:upkeep_detail", args=[item.pk]))
        self.assertEqual((item.name, item.location, item.chore.owner), ("Clean the dryer vent", "Laundry room", None))
        self.assertEqual(item.chore.occurrences.get(status=OccurrenceStatus.OPEN).due_on, date(2027, 3, 1))

    def test_errors_in_either_half_re_render_without_saving(self):
        response = self.client.post(
            reverse("household:upkeep_create"),
            form_data(**{"chore-title": "", "item-estimated_cost": "-5"}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("title", response.context["chore_form"].errors)
        self.assertIn("estimated_cost", response.context["item_form"].errors)
        self.assertFalse(Chore.objects.exists())

    def test_editing_details_keeps_an_overdue_item_overdue(self):
        item = make_item(frequency=Frequency.DAILY, interval=90, anchor=Anchor.AFTER_COMPLETION,
                         starts_on=household_today() - timedelta(days=12), today=household_today())
        overdue = item.chore.occurrences.get(status=OccurrenceStatus.OPEN)

        self.client.post(
            reverse("household:upkeep_edit", args=[item.pk]),
            form_data(**{
                "chore-title": item.name, "chore-frequency": Frequency.DAILY, "chore-interval": 90,
                "chore-anchor": Anchor.AFTER_COMPLETION,
                "chore-starts_on": item.chore.starts_on.isoformat(),
                "item-supplies": "16x25x1",
            }),
        )

        item.refresh_from_db()
        self.assertEqual(item.supplies, "16x25x1")
        self.assertEqual(item.chore.occurrences.get(status=OccurrenceStatus.OPEN).pk, overdue.pk)


class CostLogTests(TestCase):
    def setUp(self):
        self.david = make_member("david", first_name="David")
        sign_in(self.client, self.david)
        self.item = make_item(frequency=Frequency.DAILY, interval=90, anchor=Anchor.AFTER_COMPLETION,
                              starts_on=household_today(), today=household_today())
        self.current = self.item.chore.occurrences.get(status=OccurrenceStatus.OPEN)
        self.url = reverse("household:occurrence_action", args=[self.current.pk, "complete"])
        self.detail = reverse("household:upkeep_detail", args=[self.item.pk])

    def test_marking_done_records_the_cost_and_note_and_says_so(self):
        response = self.client.post(self.url, {"cost": "27.49", "note": "MERV 13", "next": self.detail}, follow=True)

        self.current.refresh_from_db()
        self.assertEqual((self.current.cost, self.current.note), (Decimal("27.49"), "MERV 13"))
        self.assertContains(response, "Marked done")
        self.assertContains(response, "$27.49")

    def test_a_bad_cost_changes_nothing(self):
        for bad in ["-1", "twelve", "1.234"]:
            with self.subTest(cost=bad):
                response = self.client.post(self.url, {"cost": bad, "next": self.detail}, follow=True)

                self.current.refresh_from_db()
                self.assertTrue(self.current.is_open)
                self.assertContains(response, "look like an amount")

    def test_undo_clears_the_cost(self):
        occurrences.complete(self.current, by=self.david, cost=Decimal("10"))
        occurrences.reopen(self.current)

        self.current.refresh_from_db()
        self.assertIsNone(self.current.cost)

    def test_spend_by_year_uses_the_household_date(self):
        chore = self.item.chore
        chore.occurrences.all().delete()
        for when, cost in [
            (at(date(2025, 6, 1)), "20.00"),
            (at(date(2026, 3, 1)), "23.49"),
            # 10:30pm on New Year's Eve in Chicago is already 2027 in UTC.
            (at(date(2026, 12, 31), hour=22), "24.99"),
        ]:
            Occurrence.objects.create(chore=chore, status=OccurrenceStatus.DONE, completed_at=when,
                                      completed_by=self.david, cost=Decimal(cost))

        self.assertEqual(
            maintenance.cost_by_year(self.item),
            [(2026, Decimal("48.48")), (2025, Decimal("20.00"))],
        )


class UpkeepPageTests(TestCase):
    def setUp(self):
        self.david = make_member("david", first_name="David")
        sign_in(self.client, self.david)

    def test_needs_attention_is_overdue_first_then_by_due_date(self):
        today = household_today()
        make_item("Later", starts_on=today + timedelta(days=20), today=today)
        make_item("Sooner", starts_on=today + timedelta(days=5), deadline_offset_days=30, today=today)
        make_item("Overdue", frequency=Frequency.DAILY, interval=90, anchor=Anchor.AFTER_COMPLETION,
                  starts_on=today - timedelta(days=3), today=today)
        make_item("Far off", starts_on=today + timedelta(days=90), today=today)

        attention = [item.name for item in maintenance.overview(today)["needs_attention"]]

        self.assertEqual(attention, ["Overdue", "Sooner", "Later"])

    def test_the_query_count_does_not_grow_with_items(self):
        def count():
            with CaptureQueriesContext(connection) as queries:
                self.client.get(reverse("household:upkeep"))
            return len(queries)

        count()
        make_item("One")
        few = count()
        for index in range(12):
            item = make_item(f"Item {index}")
            occurrences.complete(item.chore.occurrences.get(status=OccurrenceStatus.OPEN), by=self.david)

        self.assertEqual(count(), few)

    def test_maintenance_on_a_checklist_links_to_its_upkeep_page(self):
        item = make_item("Test the detectors", starts_on=household_today(), today=household_today())

        response = self.client.get(reverse("household:today"))

        self.assertContains(response, f'href="{reverse("household:upkeep_detail", args=[item.pk])}"')

    def test_deleting_an_item_deletes_its_chore_and_history(self):
        item = make_item()

        self.client.post(reverse("household:upkeep_delete", args=[item.pk]))

        self.assertFalse(Chore.objects.exists())
        self.assertFalse(Occurrence.objects.exists())


class ChorePagesForMaintenanceTests(TestCase):
    """A maintenance chore's pages are its Upkeep pages."""

    def setUp(self):
        self.item = make_item()
        self.chore = self.item.chore

    def test_a_member_is_sent_to_the_upkeep_page(self):
        sign_in(self.client, make_member("david"))

        for name, target in [
            ("household:chore_detail", "household:upkeep_detail"),
            ("household:chore_edit", "household:upkeep_edit"),
            ("household:chore_delete", "household:upkeep_delete"),
        ]:
            with self.subTest(route=name):
                response = self.client.get(reverse(name, args=[self.chore.pk]))
                self.assertRedirects(response, reverse(target, args=[self.item.pk]))

    def test_a_stranger_cannot_tell_a_maintenance_chore_from_any_other(self):
        """Regression: the redirect ran before the gate, so an outsider got a
        redirect for maintenance chores and a 403 for everything else."""
        self.client.force_login(make_member("outsider", in_group=False))

        for name in ("household:chore_detail", "household:chore_edit", "household:chore_delete"):
            with self.subTest(route=name):
                self.assertEqual(self.client.get(reverse(name, args=[self.chore.pk])).status_code, 403)

    def test_a_stranger_gets_403_for_real_and_missing_items_alike(self):
        self.client.force_login(make_member("outsider", in_group=False))

        for pk in (self.item.pk, 9999):
            with self.subTest(pk=pk):
                self.assertEqual(self.client.get(reverse("household:upkeep_detail", args=[pk])).status_code, 403)
                self.assertEqual(self.client.get(reverse("household:upkeep_edit", args=[pk])).status_code, 403)
