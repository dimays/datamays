"""Budget period boundaries.

Off-by-one errors here are invisible in the UI and quietly wrong in every
number the app reports, so the awkward cases get explicit coverage: month
lengths, leap days, year boundaries, and dates before the anchor.
"""

from datetime import date

from django.test import SimpleTestCase

from finance.periods import (
    annual_period,
    elapsed_fraction,
    monthly_period,
    next_period,
    period_containing,
    previous_period,
    weekly_period,
)


class WeeklyTests(SimpleTestCase):
    ANCHOR = date(2026, 1, 5)  # a Monday

    def test_anchor_day_starts_its_own_period(self):
        self.assertEqual(
            weekly_period(self.ANCHOR, self.ANCHOR),
            (date(2026, 1, 5), date(2026, 1, 11)),
        )

    def test_last_day_of_period_stays_in_it(self):
        self.assertEqual(
            weekly_period(self.ANCHOR, date(2026, 1, 11)),
            (date(2026, 1, 5), date(2026, 1, 11)),
        )

    def test_next_day_rolls_over(self):
        self.assertEqual(
            weekly_period(self.ANCHOR, date(2026, 1, 12)),
            (date(2026, 1, 12), date(2026, 1, 18)),
        )

    def test_dates_before_the_anchor_still_resolve(self):
        # A budget created today must still report last month correctly.
        self.assertEqual(
            weekly_period(self.ANCHOR, date(2025, 12, 30)),
            (date(2025, 12, 29), date(2026, 1, 4)),
        )

    def test_periods_tile_without_gaps_or_overlaps(self):
        start, end = weekly_period(self.ANCHOR, date(2026, 3, 18))
        self.assertEqual((end - start).days, 6)

        _, previous_end = previous_period("weekly", self.ANCHOR, start)
        next_start, _ = next_period("weekly", self.ANCHOR, end)

        self.assertEqual((start - previous_end).days, 1)
        self.assertEqual((next_start - end).days, 1)


class MonthlyTests(SimpleTestCase):
    def test_calendar_month_when_anchored_to_the_first(self):
        anchor = date(2026, 1, 1)
        self.assertEqual(
            monthly_period(anchor, date(2026, 2, 14)),
            (date(2026, 2, 1), date(2026, 2, 28)),
        )

    def test_pay_cycle_anchor_shifts_the_whole_window(self):
        # A budget that resets on the 15th, not the 1st.
        anchor = date(2026, 1, 15)
        self.assertEqual(
            monthly_period(anchor, date(2026, 3, 2)),
            (date(2026, 2, 15), date(2026, 3, 14)),
        )

    def test_day_31_anchor_clamps_in_february(self):
        anchor = date(2026, 1, 31)
        self.assertEqual(
            monthly_period(anchor, date(2026, 2, 10)),
            (date(2026, 1, 31), date(2026, 2, 27)),
        )

    def test_day_31_anchor_recovers_the_full_day_in_longer_months(self):
        anchor = date(2026, 1, 31)
        self.assertEqual(
            monthly_period(anchor, date(2026, 3, 31)),
            (date(2026, 3, 31), date(2026, 4, 29)),
        )

    def test_leap_day_is_handled(self):
        anchor = date(2024, 1, 29)
        self.assertEqual(
            monthly_period(anchor, date(2024, 2, 29)),
            (date(2024, 2, 29), date(2024, 3, 28)),
        )

    def test_december_rolls_into_january(self):
        anchor = date(2026, 1, 1)
        self.assertEqual(
            monthly_period(anchor, date(2026, 12, 20)),
            (date(2026, 12, 1), date(2026, 12, 31)),
        )

    def test_every_day_of_a_year_lands_in_exactly_one_period(self):
        anchor = date(2026, 1, 15)
        day = date(2026, 1, 1)

        while day < date(2027, 1, 1):
            start, end = monthly_period(anchor, day)
            self.assertLessEqual(start, day)
            self.assertLessEqual(day, end)
            day = date.fromordinal(day.toordinal() + 1)


class AnnualTests(SimpleTestCase):
    def test_calendar_year(self):
        anchor = date(2026, 1, 1)
        self.assertEqual(
            annual_period(anchor, date(2026, 7, 4)),
            (date(2026, 1, 1), date(2026, 12, 31)),
        )

    def test_fiscal_style_anchor(self):
        anchor = date(2020, 7, 1)
        self.assertEqual(
            annual_period(anchor, date(2026, 3, 1)),
            (date(2025, 7, 1), date(2026, 6, 30)),
        )

    def test_date_before_the_anchor_within_the_year(self):
        anchor = date(2026, 6, 1)
        self.assertEqual(
            annual_period(anchor, date(2026, 2, 1)),
            (date(2025, 6, 1), date(2026, 5, 31)),
        )


class DispatchTests(SimpleTestCase):
    def test_unknown_period_type_is_rejected(self):
        with self.assertRaises(ValueError):
            period_containing("fortnightly", date(2026, 1, 1), date(2026, 1, 1))


class ElapsedFractionTests(SimpleTestCase):
    START = date(2026, 4, 1)
    END = date(2026, 4, 30)

    def test_first_day_is_one_thirtieth_not_zero(self):
        # Day one is already partly spent, so pacing must not divide by zero
        # or claim no time has passed.
        self.assertAlmostEqual(elapsed_fraction(self.START, self.END, self.START), 1 / 30)

    def test_last_day_is_complete(self):
        self.assertEqual(elapsed_fraction(self.START, self.END, self.END), 1.0)

    def test_clamped_outside_the_period(self):
        self.assertEqual(elapsed_fraction(self.START, self.END, date(2026, 3, 1)), 0.0)
        self.assertEqual(elapsed_fraction(self.START, self.END, date(2026, 5, 15)), 1.0)

    def test_single_day_period_does_not_divide_by_zero(self):
        self.assertEqual(elapsed_fraction(self.START, self.START, self.START), 1.0)
