"""The occurrence lifecycle: open, done, skipped, missed, undone."""

from datetime import date, datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from household.models import Occurrence, OccurrenceStatus
from household.scheduling import Anchor, Frequency
from household.services import occurrences

from .factories import make_chore, make_member

CHICAGO = ZoneInfo("America/Chicago")
TODAY = date(2026, 9, 30)  # a Wednesday


def at(day, hour=12):
    """An aware datetime at `hour` o'clock Chicago time on `day`."""
    return datetime.combine(day, time(hour), tzinfo=CHICAGO)


def open_ones(chore):
    return list(chore.occurrences.filter(status=OccurrenceStatus.OPEN))


class StartTests(TestCase):
    def setUp(self):
        self.david = make_member("david")

    def test_a_one_off_opens_with_its_due_date_and_deadline(self):
        chore = make_chore(self.david, starts_on=date(2026, 10, 3), deadline=date(2026, 10, 10), today=TODAY)

        [current] = open_ones(chore)
        self.assertEqual((current.due_on, current.deadline), (date(2026, 10, 3), date(2026, 10, 10)))

    def test_a_one_off_can_be_due_whenever(self):
        chore = make_chore(self.david, starts_on=None, today=TODAY)

        [current] = open_ones(chore)
        self.assertIsNone(current.due_on)
        self.assertFalse(current.is_overdue(TODAY))

    def test_a_repeating_chore_opens_its_next_due_date(self):
        chore = make_chore(
            self.david, frequency=Frequency.WEEKLY, starts_on=date(2026, 8, 3),
            deadline_offset_days=1, today=TODAY,
        )

        [current] = open_ones(chore)
        self.assertEqual((current.due_on, current.deadline), (date(2026, 10, 5), date(2026, 10, 6)))


class CompleteTests(TestCase):
    def setUp(self):
        self.david = make_member("david")
        self.maddie = make_member("maddie")
        self.weekly = make_chore(
            self.david, frequency=Frequency.WEEKLY, starts_on=date(2026, 10, 5), today=TODAY
        )

    def test_done_records_who_when_and_why_and_opens_the_next(self):
        [current] = open_ones(self.weekly)

        following = occurrences.complete(
            current, by=self.maddie, note="Did it on my way out", now=at(date(2026, 10, 5)), today=date(2026, 10, 5)
        )

        current.refresh_from_db()
        self.assertEqual(current.status, OccurrenceStatus.DONE)
        self.assertEqual(current.completed_by, self.maddie)
        self.assertEqual(current.note, "Did it on my way out")
        self.assertEqual(following.due_on, date(2026, 10, 12))
        self.assertEqual(open_ones(self.weekly), [following])

    def test_a_double_tap_completes_once(self):
        [current] = open_ones(self.weekly)

        occurrences.complete(current, by=self.david, now=at(date(2026, 10, 5)), today=date(2026, 10, 5))
        again = occurrences.complete(current, by=self.david, now=at(date(2026, 10, 5)), today=date(2026, 10, 5))

        self.assertIsNone(again)
        self.assertEqual(len(open_ones(self.weekly)), 1)
        self.assertEqual(self.weekly.occurrences.count(), 2)

    def test_the_database_refuses_a_second_open_occurrence(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Occurrence.objects.create(chore=self.weekly, due_on=date(2026, 10, 12))

    def test_a_one_off_is_finished_once_done(self):
        chore = make_chore(self.david, starts_on=date(2026, 10, 3), today=TODAY)
        [current] = open_ones(chore)

        self.assertIsNone(occurrences.complete(current, by=self.david, now=at(TODAY), today=TODAY))
        self.assertEqual(open_ones(chore), [])

    def test_a_finished_series_opens_nothing(self):
        chore = make_chore(
            self.david, frequency=Frequency.WEEKLY, starts_on=date(2026, 10, 5),
            ends_on=date(2026, 10, 5), today=TODAY,
        )
        [current] = open_ones(chore)

        self.assertIsNone(occurrences.complete(current, by=self.david, now=at(date(2026, 10, 5)), today=date(2026, 10, 5)))

    def test_done_very_late_opens_the_newest_arrived_date(self):
        daily = make_chore(self.david, frequency=Frequency.DAILY, starts_on=date(2026, 10, 1), today=date(2026, 10, 1))
        [current] = open_ones(daily)

        following = occurrences.complete(current, by=self.david, now=at(date(2026, 10, 8)), today=date(2026, 10, 8))

        self.assertEqual(following.due_on, date(2026, 10, 8))


class AfterCompletionTests(TestCase):
    def setUp(self):
        self.david = make_member("david")
        self.filter = make_chore(
            None, title="Replace furnace filter", frequency=Frequency.DAILY, interval=90,
            anchor=Anchor.AFTER_COMPLETION, starts_on=date(2026, 9, 1), today=TODAY,
        )

    def test_the_clock_restarts_on_the_day_it_was_done(self):
        [current] = open_ones(self.filter)
        self.assertTrue(current.is_overdue(TODAY))

        following = occurrences.complete(current, by=self.david, now=at(TODAY), today=TODAY)

        self.assertEqual(following.due_on, date(2026, 12, 29))

    def test_done_late_in_the_evening_counts_for_that_household_day(self):
        """10:30pm in Chicago is already tomorrow in UTC — it must not count as tomorrow."""
        [current] = open_ones(self.filter)
        late_evening = at(TODAY, hour=22).replace(minute=30)
        self.assertEqual(late_evening.astimezone(ZoneInfo("UTC")).date(), date(2026, 10, 1))

        following = occurrences.complete(current, by=self.david, now=late_evening, today=TODAY)

        self.assertEqual(following.due_on, date(2026, 12, 29))

    def test_a_skip_restarts_the_clock_too(self):
        [current] = open_ones(self.filter)

        following = occurrences.skip(current, by=self.david, now=at(TODAY), today=TODAY)

        current.refresh_from_db()
        self.assertEqual(current.status, OccurrenceStatus.SKIPPED)
        self.assertEqual(following.due_on, date(2026, 12, 29))

    def test_it_is_never_missed_only_overdue(self):
        chores = occurrences.with_open_occurrence(type(self.filter).objects.all())
        occurrences.refresh(chores, today=date(2027, 6, 1))

        [current] = open_ones(self.filter)
        self.assertEqual(current.due_on, date(2026, 9, 1))
        self.assertEqual(current.days_overdue(date(2026, 9, 30)), 29)

    def test_a_count_limit_ends_the_series(self):
        chore = make_chore(
            None, frequency=Frequency.WEEKLY, anchor=Anchor.AFTER_COMPLETION,
            starts_on=TODAY, max_occurrences=2, today=TODAY,
        )

        second = occurrences.complete(open_ones(chore)[0], by=self.david, now=at(TODAY), today=TODAY)
        third = occurrences.complete(second, by=self.david, now=at(date(2026, 10, 7)), today=date(2026, 10, 7))

        self.assertIsNotNone(second)
        self.assertIsNone(third)


class CollapseTests(TestCase):
    def setUp(self):
        self.david = make_member("david")
        self.weekly = make_chore(
            self.david, frequency=Frequency.WEEKLY, starts_on=date(2026, 10, 5), today=TODAY
        )

    def refreshed(self, today):
        chores = occurrences.with_open_occurrence(type(self.weekly).objects.all())
        return occurrences.refresh(chores, today=today)

    def test_nothing_changes_before_the_next_due_date(self):
        self.refreshed(date(2026, 10, 11))

        [current] = open_ones(self.weekly)
        self.assertEqual(current.due_on, date(2026, 10, 5))
        self.assertTrue(current.is_overdue(date(2026, 10, 11)))

    def test_an_arrived_due_date_misses_the_old_one(self):
        [chore] = self.refreshed(date(2026, 10, 20))

        statuses = list(self.weekly.occurrences.order_by("due_on").values_list("due_on", "status"))
        # Every date that came and went is recorded as missed — the 12th
        # too, though nothing ever opened for it — and only the newest opens.
        self.assertEqual(
            statuses,
            [
                (date(2026, 10, 5), OccurrenceStatus.MISSED),
                (date(2026, 10, 12), OccurrenceStatus.MISSED),
                (date(2026, 10, 19), OccurrenceStatus.OPEN),
            ],
        )
        # The caller's copy is updated in place, ready to render.
        self.assertEqual(chore.open_occurrences[0].due_on, date(2026, 10, 19))

    def test_the_query_count_does_not_grow_with_the_number_of_chores(self):
        for index in range(10):
            make_chore(self.david, title=f"Chore {index}", frequency=Frequency.DAILY, starts_on=TODAY, today=TODAY)

        with self.assertNumQueries(2):
            self.refreshed(TODAY)

    def test_the_sweep_command_applies_the_same_rule(self):
        with patch("household.services.occurrences.household_today", return_value=date(2026, 10, 20)):
            call_command("sweep_chores", verbosity=0)

        [current] = open_ones(self.weekly)
        self.assertEqual(current.due_on, date(2026, 10, 19))


class ReopenTests(TestCase):
    def setUp(self):
        self.david = make_member("david")
        self.weekly = make_chore(
            self.david, frequency=Frequency.WEEKLY, starts_on=date(2026, 10, 5), today=TODAY
        )

    def test_an_accidental_tap_can_be_undone(self):
        [current] = open_ones(self.weekly)
        occurrences.complete(current, by=self.david, now=at(date(2026, 10, 5)), today=date(2026, 10, 5))

        self.assertTrue(occurrences.reopen(current))

        current.refresh_from_db()
        self.assertTrue(current.is_open)
        self.assertIsNone(current.completed_by)
        self.assertEqual(open_ones(self.weekly), [current])

    def test_older_history_stands(self):
        [first] = open_ones(self.weekly)
        second = occurrences.complete(first, by=self.david, now=at(date(2026, 10, 5)), today=date(2026, 10, 5))
        occurrences.complete(second, by=self.david, now=at(date(2026, 10, 12)), today=date(2026, 10, 12))

        self.assertFalse(occurrences.reopen(first))
        self.assertFalse(occurrences.reopen(open_ones(self.weekly)[0]))


class RescheduleTests(TestCase):
    def setUp(self):
        self.david = make_member("david")

    def test_a_new_weekday_replaces_the_open_occurrence(self):
        chore = make_chore(self.david, frequency=Frequency.WEEKLY, starts_on=date(2026, 10, 5), today=TODAY)

        chore.starts_on = date(2026, 10, 8)
        chore.save()
        occurrences.reschedule(chore, today=TODAY)

        [current] = open_ones(chore)
        self.assertEqual(current.due_on, date(2026, 10, 8))
        self.assertEqual(chore.occurrences.count(), 1)

    def test_pausing_takes_it_off_the_list_and_resuming_starts_afresh(self):
        chore = make_chore(self.david, frequency=Frequency.WEEKLY, starts_on=date(2026, 9, 7), today=date(2026, 9, 7))

        chore.is_active = False
        occurrences.reschedule(chore, today=TODAY)
        self.assertEqual(open_ones(chore), [])

        chore.is_active = True
        occurrences.reschedule(chore, today=TODAY)
        [current] = open_ones(chore)
        self.assertEqual(current.due_on, date(2026, 10, 5))

    def test_after_completion_remembers_when_it_was_last_done(self):
        chore = make_chore(
            None, frequency=Frequency.DAILY, interval=90, anchor=Anchor.AFTER_COMPLETION,
            starts_on=date(2026, 9, 1), today=TODAY,
        )
        occurrences.complete(open_ones(chore)[0], by=self.david, now=at(TODAY), today=TODAY)

        chore.interval = 60
        occurrences.reschedule(chore, today=TODAY)

        [current] = open_ones(chore)
        self.assertEqual(current.due_on, date(2026, 11, 29))

    def test_a_one_off_moves_its_date(self):
        chore = make_chore(self.david, starts_on=date(2026, 10, 3), today=TODAY)

        chore.starts_on = date(2026, 10, 4)
        occurrences.reschedule(chore, today=TODAY)

        [current] = open_ones(chore)
        self.assertEqual(current.due_on, date(2026, 10, 4))

    def test_a_done_one_off_stays_done_until_given_a_new_date(self):
        chore = make_chore(self.david, starts_on=date(2026, 10, 3), today=TODAY)
        occurrences.complete(open_ones(chore)[0], by=self.david, now=at(TODAY), today=TODAY)

        occurrences.reschedule(chore, today=TODAY)
        self.assertEqual(open_ones(chore), [])

        # "Do it again on the 10th."
        chore.starts_on = date(2026, 10, 10)
        occurrences.reschedule(chore, today=TODAY)
        [current] = open_ones(chore)
        self.assertEqual(current.due_on, date(2026, 10, 10))

    def test_a_finished_series_converted_to_a_one_off_goes_back_on_the_list(self):
        """Found in review: it used to be left active but on no checklist."""
        chore = make_chore(
            self.david, frequency=Frequency.WEEKLY, starts_on=date(2026, 9, 28),
            ends_on=date(2026, 9, 28), today=date(2026, 9, 28),
        )
        occurrences.complete(open_ones(chore)[0], by=self.david, now=at(date(2026, 9, 28)), today=date(2026, 9, 28))
        self.assertEqual(open_ones(chore), [])

        chore.frequency = Frequency.ONCE
        chore.ends_on = None
        chore.starts_on = date(2026, 11, 1)
        occurrences.reschedule(chore, today=TODAY)

        [current] = open_ones(chore)
        self.assertEqual(current.due_on, date(2026, 11, 1))


class OverdueTests(TestCase):
    def test_due_today_is_not_overdue_and_a_deadline_extends_it(self):
        david = make_member("david")
        plain = make_chore(david, starts_on=TODAY, today=TODAY)
        with_deadline = make_chore(david, title="Renew plates", starts_on=date(2026, 9, 20),
                                   deadline=date(2026, 9, 30), today=TODAY)

        [plain_one] = open_ones(plain)
        [deadline_one] = open_ones(with_deadline)

        self.assertFalse(plain_one.is_overdue(TODAY))
        self.assertTrue(plain_one.is_overdue(date(2026, 10, 1)))
        self.assertEqual(plain_one.days_overdue(date(2026, 10, 3)), 3)
        self.assertFalse(deadline_one.is_overdue(TODAY))
        self.assertTrue(deadline_one.is_overdue(date(2026, 10, 1)))


class ChoreValidationTests(TestCase):
    def assertInvalid(self, field, **kwargs):
        from django.core.exceptions import ValidationError

        from household.models import Chore

        with self.assertRaises(ValidationError) as caught:
            Chore(title="x", **kwargs).clean()
        self.assertIn(field, caught.exception.message_dict)

    def test_the_combinations_that_make_no_sense(self):
        cases = [
            ("season_start_month", {"frequency": Frequency.MONTHLY, "starts_on": TODAY, "season_start_month": 4}),
            ("deadline", {"frequency": Frequency.WEEKLY, "starts_on": TODAY, "deadline": TODAY}),
            ("deadline_offset_days", {"starts_on": TODAY, "deadline_offset_days": 2}),
            ("deadline", {"starts_on": TODAY, "deadline": date(2026, 9, 1)}),
            ("starts_on", {"frequency": Frequency.DAILY, "starts_on": None}),
        ]
        for field, kwargs in cases:
            with self.subTest(field=field, **{k: str(v) for k, v in kwargs.items()}):
                self.assertInvalid(field, **kwargs)

    def test_the_describe_shortcut(self):
        from household.models import Chore

        chore = Chore(title="x", frequency=Frequency.MONTHLY, starts_on=date(2026, 4, 1),
                      season_start_month=4, season_end_month=10)
        self.assertEqual(chore.describe_schedule(), "Monthly on day 1, Apr–Oct")


class CountOriginTests(TestCase):
    def test_a_past_start_does_not_use_up_the_count(self):
        """Found in review: "ten times" from a June start, created in
        September, used to open nothing at all."""
        chore = make_chore(
            make_member("david"), frequency=Frequency.WEEKLY, starts_on=date(2026, 6, 1),
            max_occurrences=10, today=TODAY,
        )
        # Created "on" TODAY for counting purposes.
        chore.created_at = at(TODAY)

        from household.scheduling import fixed_dates

        future = [day for day in fixed_dates(chore.schedule) if day >= TODAY]
        self.assertEqual(len(future), 10)
        self.assertEqual(future[0], date(2026, 10, 5))


class EditPathTests(TestCase):
    """Round-1 review: editing a chore must not resurrect, ignore, or drop it."""

    def setUp(self):
        self.david = make_member("david")

    def test_an_edit_never_reopens_a_date_already_done(self):
        chore = make_chore(self.david, frequency=Frequency.WEEKLY, starts_on=date(2026, 10, 5),
                           today=date(2026, 10, 5))
        occurrences.complete(open_ones(chore)[0], by=self.david, now=at(date(2026, 10, 5)), today=date(2026, 10, 5))
        before = type(chore).objects.get(pk=chore.pk)

        chore.deadline_offset_days = 2
        chore.save()
        occurrences.apply_edit(chore, before, today=date(2026, 10, 5))

        [current] = open_ones(chore)
        self.assertEqual(current.due_on, date(2026, 10, 12))
        self.assertEqual(current.deadline, date(2026, 10, 14))

    def test_pausing_and_resuming_after_todays_is_done_keeps_it_done(self):
        chore = make_chore(self.david, frequency=Frequency.DAILY, starts_on=TODAY, today=TODAY)
        occurrences.complete(open_ones(chore)[0], by=self.david, now=at(TODAY), today=TODAY)

        for active in (False, True):
            before = type(chore).objects.get(pk=chore.pk)
            chore.is_active = active
            chore.save()
            occurrences.apply_edit(chore, before, today=TODAY)

        [current] = open_ones(chore)
        self.assertEqual(current.due_on, TODAY + timedelta(days=1))

    def test_changing_only_a_one_offs_deadline_moves_it(self):
        chore = make_chore(self.david, starts_on=TODAY, deadline=TODAY + timedelta(days=30), today=TODAY)
        before = type(chore).objects.get(pk=chore.pk)

        chore.deadline = TODAY + timedelta(days=2)
        chore.save()
        occurrences.apply_edit(chore, before, today=TODAY)

        self.assertEqual(open_ones(chore)[0].deadline, TODAY + timedelta(days=2))

    def test_a_title_edit_changes_nothing(self):
        chore = make_chore(self.david, frequency=Frequency.WEEKLY, starts_on=date(2026, 9, 7),
                           today=date(2026, 9, 7))
        [overdue] = open_ones(chore)
        before = type(chore).objects.get(pk=chore.pk)

        chore.title = "Bins and recycling"
        chore.save()
        self.assertIsNone(occurrences.apply_edit(chore, before, today=TODAY))
        self.assertEqual(open_ones(chore), [overdue])

    def test_a_schedule_change_restarts_the_occurrence_limit(self):
        """It used to burn the count on dates from before the edit, and the
        chore vanished from every list."""
        chore = make_chore(self.david, frequency=Frequency.WEEKLY, starts_on=date(2026, 9, 1),
                           max_occurrences=5, today=date(2026, 9, 1))
        before = type(chore).objects.get(pk=chore.pk)

        chore.frequency = Frequency.DAILY
        chore.save()
        occurrences.apply_edit(chore, before, today=date(2026, 9, 30))

        [current] = open_ones(chore)
        self.assertEqual(current.due_on, date(2026, 9, 30))
        self.assertEqual(chore.schedule_set_on, date(2026, 9, 30))

    def test_a_one_off_done_early_then_made_weekly_starts_now(self):
        """Round 2: the fresh start waited until after the one-off's old due
        date, three months out."""
        chore = make_chore(self.david, starts_on=TODAY + timedelta(days=90), today=TODAY)
        occurrences.complete(open_ones(chore)[0], by=self.david, now=at(TODAY), today=TODAY)
        before = type(chore).objects.get(pk=chore.pk)

        chore.frequency = Frequency.WEEKLY
        chore.starts_on = TODAY
        chore.save()
        occurrences.apply_edit(chore, before, today=TODAY)

        self.assertEqual(open_ones(chore)[0].due_on, TODAY)

    def test_a_date_done_early_is_still_passed_over(self):
        friday = date(2026, 10, 2)
        chore = make_chore(self.david, frequency=Frequency.WEEKLY, starts_on=friday, today=TODAY)
        occurrences.complete(open_ones(chore)[0], by=self.david, now=at(TODAY), today=TODAY)

        for active in (False, True):
            before = type(chore).objects.get(pk=chore.pk)
            chore.is_active = active
            chore.save()
            occurrences.apply_edit(chore, before, today=TODAY)

        self.assertEqual(open_ones(chore)[0].due_on, friday + timedelta(days=7))

    def test_an_after_completion_limit_counts_from_the_change_too(self):
        """Round 2: the whole history counted, so changing a long-running
        chore to "3 times" opened nothing and it vanished."""
        chore = make_chore(None, frequency=Frequency.DAILY, starts_on=date(2026, 9, 1), today=date(2026, 9, 1))
        for day in range(1, 11):
            occurrences.complete(open_ones(chore)[0], by=self.david, now=at(date(2026, 9, day)),
                                 today=date(2026, 9, day))
        chore.occurrences.update(created_at=at(date(2026, 9, 1)))  # opened on earlier days
        before = type(chore).objects.get(pk=chore.pk)

        chore.anchor = Anchor.AFTER_COMPLETION
        chore.interval = 7
        chore.max_occurrences = 3
        chore.save()
        occurrences.apply_edit(chore, before, today=TODAY)

        done = 0
        while open_ones(chore):
            done += 1
            occurrences.complete(open_ones(chore)[0], by=self.david, now=at(TODAY), today=TODAY)
        self.assertEqual(done, 3)

    def test_an_overdue_occurrence_replaced_by_an_edit_is_recorded_as_missed(self):
        """Round 2: the edit deleted it, and the miss vanished from history."""
        chore = make_chore(self.david, frequency=Frequency.WEEKLY, starts_on=date(2026, 9, 21),
                           today=date(2026, 9, 21))
        [overdue] = open_ones(chore)
        before = type(chore).objects.get(pk=chore.pk)

        chore.frequency = Frequency.DAILY
        chore.save()
        occurrences.apply_edit(chore, before, today=TODAY)

        overdue.refresh_from_db()
        self.assertEqual(overdue.status, OccurrenceStatus.MISSED)
        self.assertEqual(open_ones(chore)[0].due_on, TODAY)

    def test_raising_an_ended_after_completion_chores_limit_revives_it(self):
        chore = make_chore(None, frequency=Frequency.MONTHLY, anchor=Anchor.AFTER_COMPLETION,
                           starts_on=date(2026, 7, 1), max_occurrences=2, today=date(2026, 7, 1))
        for day in (date(2026, 7, 1), date(2026, 8, 1)):
            occurrences.complete(open_ones(chore)[0], by=self.david, now=at(day), today=day)
        self.assertEqual(open_ones(chore), [])
        chore.occurrences.update(created_at=at(date(2026, 7, 1)))
        before = type(chore).objects.get(pk=chore.pk)

        chore.max_occurrences = 4
        chore.save()
        occurrences.apply_edit(chore, before, today=TODAY)

        self.assertEqual(open_ones(chore)[0].due_on, date(2026, 9, 1))

    def test_a_new_due_date_on_an_after_completion_chore_is_honored(self):
        chore = make_chore(None, frequency=Frequency.DAILY, interval=90, anchor=Anchor.AFTER_COMPLETION,
                           starts_on=date(2026, 9, 1), today=TODAY)
        occurrences.complete(open_ones(chore)[0], by=self.david, now=at(date(2026, 9, 10)), today=date(2026, 9, 10))
        before = type(chore).objects.get(pk=chore.pk)

        chore.starts_on = date(2026, 11, 1)
        chore.save()
        occurrences.apply_edit(chore, before, today=TODAY)

        self.assertEqual(open_ones(chore)[0].due_on, date(2026, 11, 1))
