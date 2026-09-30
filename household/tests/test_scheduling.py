"""Schedule arithmetic, boundary by boundary.

Every plausible off-by-one gets its own case: month-end days, leap years, a
fifth weekday that some months lack, seasons that wrap the new year, and the
difference between "on" and "after" a date. The dates are chosen, not random —
each comment says what the case is there to catch.
"""

from datetime import date
from itertools import islice

from django.test import SimpleTestCase

from household.scheduling import (
    Anchor,
    Frequency,
    MonthlyMode,
    Schedule,
    deadline_for,
    describe,
    first_due,
    fixed_dates,
    in_season,
    next_after_completion,
    next_due,
    next_fixed_after,
    superseding_due,
    validate,
)


def dates(schedule, count=6):
    return list(islice(fixed_dates(schedule), count))


def weekly(starts_on, *weekdays, **kwargs):
    return Schedule(Frequency.WEEKLY, starts_on, weekdays=weekdays, **kwargs)


def monthly(starts_on, mode=MonthlyMode.DAY, **kwargs):
    return Schedule(Frequency.MONTHLY, starts_on, monthly_mode=mode, **kwargs)


def after(frequency, starts_on, interval, **kwargs):
    return Schedule(frequency, starts_on, interval=interval, anchor=Anchor.AFTER_COMPLETION, **kwargs)


class DailyTests(SimpleTestCase):
    def test_every_day(self):
        self.assertEqual(
            dates(Schedule(Frequency.DAILY, date(2026, 12, 30)), 4),
            [date(2026, 12, 30), date(2026, 12, 31), date(2027, 1, 1), date(2027, 1, 2)],
        )

    def test_every_third_day_crosses_a_month_end(self):
        self.assertEqual(
            dates(Schedule(Frequency.DAILY, date(2026, 1, 28), interval=3), 3),
            [date(2026, 1, 28), date(2026, 1, 31), date(2026, 2, 3)],
        )


class WeeklyTests(SimpleTestCase):
    def test_the_start_date_sets_the_weekday(self):
        # 2026-09-30 is a Wednesday.
        self.assertEqual(
            dates(weekly(date(2026, 9, 30)), 3),
            [date(2026, 9, 30), date(2026, 10, 7), date(2026, 10, 14)],
        )

    def test_several_weekdays_in_order(self):
        # Mon and Thu, starting Monday 2026-10-05.
        self.assertEqual(
            dates(weekly(date(2026, 10, 5), 3, 0), 4),
            [date(2026, 10, 5), date(2026, 10, 8), date(2026, 10, 12), date(2026, 10, 15)],
        )

    def test_weekdays_before_the_start_in_the_first_week_are_skipped(self):
        # Starts Wednesday; Monday of that week has not "happened" yet.
        self.assertEqual(
            dates(weekly(date(2026, 9, 30), 0, 4), 3),
            [date(2026, 10, 2), date(2026, 10, 5), date(2026, 10, 9)],
        )

    def test_every_other_week_keeps_its_phase(self):
        self.assertEqual(
            dates(weekly(date(2026, 9, 28), 0, interval=2), 3),
            [date(2026, 9, 28), date(2026, 10, 12), date(2026, 10, 26)],
        )


class MonthlyTests(SimpleTestCase):
    def test_the_31st_lands_on_each_months_last_day(self):
        """What rrule gets wrong: it would skip Feb, Apr, Jun."""
        self.assertEqual(
            dates(monthly(date(2026, 1, 31)), 6),
            [
                date(2026, 1, 31),
                date(2026, 2, 28),
                date(2026, 3, 31),
                date(2026, 4, 30),
                date(2026, 5, 31),
                date(2026, 6, 30),
            ],
        )

    def test_the_29th_in_a_leap_february(self):
        self.assertEqual(
            dates(monthly(date(2028, 1, 29)), 3),
            [date(2028, 1, 29), date(2028, 2, 29), date(2028, 3, 29)],
        )

    def test_every_three_months_crosses_the_new_year(self):
        self.assertEqual(
            dates(monthly(date(2026, 11, 15), interval=3), 3),
            [date(2026, 11, 15), date(2027, 2, 15), date(2027, 5, 15)],
        )

    def test_the_second_saturday(self):
        # 2026-10-10 is the second Saturday of October.
        self.assertEqual(
            dates(monthly(date(2026, 10, 10), MonthlyMode.NTH_WEEKDAY), 3),
            [date(2026, 10, 10), date(2026, 11, 14), date(2026, 12, 12)],
        )

    def test_a_fifth_weekday_skips_months_that_lack_one(self):
        # 2026-09-29 is the fifth Tuesday of September. October, November,
        # January, and February have four Tuesdays; December and March have
        # five.
        self.assertEqual(
            dates(monthly(date(2026, 9, 29), MonthlyMode.NTH_WEEKDAY), 3),
            [date(2026, 9, 29), date(2026, 12, 29), date(2027, 3, 30)],
        )

    def test_the_last_friday(self):
        # 2026-10-30 is the last Friday of October; January's is the 29th.
        self.assertEqual(
            dates(monthly(date(2026, 10, 30), MonthlyMode.LAST_WEEKDAY), 4),
            [date(2026, 10, 30), date(2026, 11, 27), date(2026, 12, 25), date(2027, 1, 29)],
        )


class YearlyTests(SimpleTestCase):
    def test_same_date_each_year(self):
        self.assertEqual(
            dates(Schedule(Frequency.YEARLY, date(2026, 4, 15)), 2),
            [date(2026, 4, 15), date(2027, 4, 15)],
        )

    def test_february_29_falls_on_the_28th_in_common_years(self):
        self.assertEqual(
            dates(Schedule(Frequency.YEARLY, date(2028, 2, 29)), 5),
            [
                date(2028, 2, 29),
                date(2029, 2, 28),
                date(2030, 2, 28),
                date(2031, 2, 28),
                date(2032, 2, 29),
            ],
        )


class LimitTests(SimpleTestCase):
    def test_the_end_date_is_inclusive(self):
        schedule = weekly(date(2026, 10, 5), ends_on=date(2026, 10, 19))
        self.assertEqual(dates(schedule, 10), [date(2026, 10, 5), date(2026, 10, 12), date(2026, 10, 19)])

    def test_a_count_limits_occurrences(self):
        schedule = Schedule(Frequency.DAILY, date(2026, 10, 1), max_occurrences=2)
        self.assertEqual(dates(schedule, 10), [date(2026, 10, 1), date(2026, 10, 2)])

    def test_a_season_filters_dates(self):
        # Monthly on the 1st, April to October only.
        schedule = monthly(date(2026, 9, 1), season=(4, 10))
        self.assertEqual(
            dates(schedule, 3), [date(2026, 9, 1), date(2026, 10, 1), date(2027, 4, 1)]
        )

    def test_a_season_can_wrap_the_new_year(self):
        schedule = monthly(date(2026, 10, 15), season=(11, 2))
        self.assertEqual(
            dates(schedule, 5),
            [
                date(2026, 11, 15),
                date(2026, 12, 15),
                date(2027, 1, 15),
                date(2027, 2, 15),
                date(2027, 11, 15),
            ],
        )

    def test_the_count_only_counts_in_season_dates(self):
        schedule = monthly(date(2026, 10, 1), season=(4, 10), max_occurrences=2)
        self.assertEqual(dates(schedule, 10), [date(2026, 10, 1), date(2027, 4, 1)])

    def test_in_season_boundaries(self):
        self.assertTrue(in_season(date(2026, 4, 1), (4, 10)))
        self.assertTrue(in_season(date(2026, 10, 31), (4, 10)))
        self.assertFalse(in_season(date(2026, 3, 31), (4, 10)))
        self.assertTrue(in_season(date(2026, 1, 1), (11, 2)))
        self.assertFalse(in_season(date(2026, 3, 1), (11, 2)))


class FixedQuestionTests(SimpleTestCase):
    def test_next_is_strictly_after(self):
        schedule = weekly(date(2026, 10, 5))
        self.assertEqual(next_fixed_after(schedule, date(2026, 10, 5)), date(2026, 10, 12))
        self.assertEqual(next_fixed_after(schedule, date(2026, 10, 6)), date(2026, 10, 12))

    def test_nothing_supersedes_until_the_next_due_date_arrives(self):
        schedule = weekly(date(2026, 10, 5))
        self.assertIsNone(superseding_due(schedule, date(2026, 10, 5), date(2026, 10, 11)))
        self.assertEqual(
            superseding_due(schedule, date(2026, 10, 5), date(2026, 10, 12)), date(2026, 10, 12)
        )

    def test_a_long_absence_collapses_to_the_newest(self):
        schedule = Schedule(Frequency.DAILY, date(2026, 10, 1))
        self.assertEqual(
            superseding_due(schedule, date(2026, 10, 1), date(2026, 10, 8)), date(2026, 10, 8)
        )

    def test_a_past_start_begins_from_today_not_already_overdue(self):
        schedule = weekly(date(2026, 8, 3))  # Mondays since August
        # Today is Wednesday 2026-09-30: the next Monday, not last Monday.
        self.assertEqual(first_due(schedule, date(2026, 9, 30)), date(2026, 10, 5))
        # On a Monday, today's.
        self.assertEqual(first_due(schedule, date(2026, 9, 28)), date(2026, 9, 28))

    def test_a_future_start_begins_on_the_start(self):
        schedule = weekly(date(2026, 11, 2))
        self.assertEqual(first_due(schedule, date(2026, 9, 30)), date(2026, 11, 2))

    def test_done_late_or_early_the_calendar_decides(self):
        schedule = weekly(date(2026, 10, 5))

        early = next_due(schedule, previous_due=date(2026, 10, 12), done_on=date(2026, 10, 10), occurrences_so_far=2)
        late = next_due(schedule, previous_due=date(2026, 10, 12), done_on=date(2026, 10, 14), occurrences_so_far=2)

        self.assertEqual(early, date(2026, 10, 19))
        self.assertEqual(late, date(2026, 10, 19))

    def test_a_finished_series_has_no_next(self):
        schedule = weekly(date(2026, 10, 5), ends_on=date(2026, 10, 12))
        self.assertIsNone(
            next_due(schedule, previous_due=date(2026, 10, 12), done_on=date(2026, 10, 12), occurrences_so_far=2)
        )


class AfterCompletionTests(SimpleTestCase):
    def test_the_clock_restarts_when_the_work_is_done(self):
        schedule = after(Frequency.DAILY, date(2026, 1, 1), 90)
        # Done three weeks late: the next is 90 days after it was actually done.
        self.assertEqual(
            next_after_completion(schedule, date(2026, 4, 21), 1), date(2026, 7, 20)
        )

    def test_months_clamp_like_everywhere_else(self):
        schedule = after(Frequency.MONTHLY, date(2026, 1, 31), 1)
        self.assertEqual(next_after_completion(schedule, date(2026, 1, 31), 1), date(2026, 2, 28))

    def test_it_waits_for_the_season_to_open(self):
        schedule = after(Frequency.DAILY, date(2026, 4, 1), 90, season=(4, 10))
        # Done Oct 20 + 90 days = Jan 18, out of season → April 1.
        self.assertEqual(next_after_completion(schedule, date(2026, 10, 20), 1), date(2027, 4, 1))

    def test_ends_and_counts_stop_it(self):
        ending = after(Frequency.WEEKLY, date(2026, 10, 1), 2, ends_on=date(2026, 10, 20))
        counted = after(Frequency.WEEKLY, date(2026, 10, 1), 2, max_occurrences=3)

        self.assertIsNone(next_after_completion(ending, date(2026, 10, 10), 1))
        self.assertEqual(next_after_completion(counted, date(2026, 10, 10), 2), date(2026, 10, 24))
        self.assertIsNone(next_after_completion(counted, date(2026, 10, 24), 3))

    def test_the_first_due_is_the_start_even_in_the_past(self):
        """An overdue filter is overdue — it has not been done since."""
        schedule = after(Frequency.DAILY, date(2026, 9, 1), 90)
        self.assertEqual(first_due(schedule, date(2026, 9, 30)), date(2026, 9, 1))


class OneOffTests(SimpleTestCase):
    def test_a_one_off_is_due_when_it_says_and_never_again(self):
        schedule = Schedule(Frequency.ONCE, date(2026, 10, 3))
        self.assertEqual(first_due(schedule, date(2026, 9, 30)), date(2026, 10, 3))
        self.assertIsNone(
            next_due(schedule, previous_due=date(2026, 10, 3), done_on=date(2026, 10, 3), occurrences_so_far=1)
        )
        self.assertEqual(list(fixed_dates(schedule)), [])

    def test_a_one_off_can_be_whenever(self):
        self.assertIsNone(first_due(Schedule(Frequency.ONCE, None), date(2026, 9, 30)))


class DeadlineTests(SimpleTestCase):
    def test_an_offset_from_each_due_date(self):
        schedule = weekly(date(2026, 10, 5), deadline_offset_days=2)
        self.assertEqual(deadline_for(schedule, date(2026, 10, 12)), date(2026, 10, 14))

    def test_no_offset_no_deadline(self):
        self.assertIsNone(deadline_for(weekly(date(2026, 10, 5)), date(2026, 10, 12)))
        self.assertIsNone(deadline_for(weekly(date(2026, 10, 5), deadline_offset_days=2), None))


class DescribeTests(SimpleTestCase):
    def test_the_words(self):
        cases = [
            (Schedule(Frequency.ONCE, date(2026, 10, 3)), "Once"),
            (Schedule(Frequency.DAILY, date(2026, 10, 3)), "Daily"),
            (weekly(date(2026, 10, 5), 0, 3, interval=2), "Every 2 weeks on Mon, Thu"),
            (weekly(date(2026, 9, 30)), "Weekly on Wed"),
            (monthly(date(2026, 1, 31)), "Monthly on day 31"),
            (monthly(date(2026, 10, 10), MonthlyMode.NTH_WEEKDAY), "Monthly on the second Saturday"),
            (monthly(date(2026, 10, 30), MonthlyMode.LAST_WEEKDAY), "Monthly on the last Friday"),
            (Schedule(Frequency.YEARLY, date(2026, 4, 15)), "Yearly on Apr 15"),
            (after(Frequency.DAILY, date(2026, 1, 1), 90), "90 days after it was last done"),
            (after(Frequency.MONTHLY, date(2026, 1, 1), 1), "1 month after it was last done"),
            (monthly(date(2026, 4, 1), season=(4, 10)), "Monthly on day 1, Apr–Oct"),
            (
                weekly(date(2026, 10, 5), max_occurrences=4, ends_on=date(2026, 12, 1)),
                "Weekly on Mon, 4 times, until Dec 1, 2026",
            ),
        ]
        for schedule, words in cases:
            with self.subTest(words=words):
                self.assertEqual(describe(schedule), words)


class ValidationTests(SimpleTestCase):
    def test_a_valid_schedule_has_no_errors(self):
        self.assertEqual(validate(weekly(date(2026, 10, 5), 0, 3)), {})
        self.assertEqual(validate(Schedule(Frequency.ONCE, None)), {})

    def test_each_problem_names_its_field(self):
        cases = [
            (Schedule(Frequency.WEEKLY, None), "starts_on"),
            (Schedule(Frequency.DAILY, date(2026, 10, 5), interval=0), "interval"),
            (Schedule(Frequency.DAILY, date(2026, 10, 5), weekdays=(1,)), "weekdays"),
            (weekly(date(2026, 10, 5), 7), "weekdays"),
            (after(Frequency.WEEKLY, date(2026, 10, 5), 1, weekdays=(0,)), "weekdays"),
            (monthly(date(2026, 10, 5), season=(0, 13)), "season_start_month"),
            (weekly(date(2026, 10, 5), ends_on=date(2026, 10, 1)), "ends_on"),
            (weekly(date(2026, 10, 5), max_occurrences=0), "max_occurrences"),
            (weekly(date(2026, 10, 5), deadline_offset_days=-1), "deadline_offset_days"),
        ]
        for schedule, field in cases:
            with self.subTest(field=field, schedule=schedule):
                self.assertIn(field, validate(schedule))
