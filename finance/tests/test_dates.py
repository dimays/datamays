"""What "today" means for this household.

TIME_ZONE is UTC, which is right for storage and for the public site. It is
wrong for a budget: between roughly 7pm and midnight Chicago time UTC has
already rolled over, so an evening grocery run on the last day of a month
landed in the next month's budget.
"""

from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase, override_settings

from finance.dates import household_start_of_day, household_today, to_household_date
from finance.models import Budget

# 20:30 on 31 August in Chicago is 01:30 on 1 September in UTC.
LATE_EVENING = datetime(2026, 9, 1, 1, 30, tzinfo=ZoneInfo("UTC"))


class HouseholdDateTests(SimpleTestCase):
    def test_a_late_evening_in_chicago_is_still_today(self):
        with patch("finance.dates.timezone.now", return_value=LATE_EVENING):
            self.assertEqual(household_today(), date(2026, 8, 31))

    def test_midday_is_unambiguous(self):
        instant = datetime(2026, 8, 31, 17, 0, tzinfo=ZoneInfo("UTC"))

        with patch("finance.dates.timezone.now", return_value=instant):
            self.assertEqual(household_today(), date(2026, 8, 31))

    def test_the_timezone_is_configurable(self):
        with override_settings(FINANCE_TIME_ZONE="UTC"):
            with patch("finance.dates.timezone.now", return_value=LATE_EVENING):
                self.assertEqual(household_today(), date(2026, 9, 1))

    def test_aware_datetimes_convert(self):
        self.assertEqual(to_household_date(LATE_EVENING), date(2026, 8, 31))
        self.assertIsNone(to_household_date(None))


class StartOfDayTests(TestCase):
    """Balance snapshots are dated; Account.balance_as_of is a datetime."""

    def test_it_returns_an_aware_datetime_on_the_same_household_date(self):
        result = household_start_of_day(date(2026, 8, 31))

        self.assertIsNotNone(result.tzinfo)
        self.assertEqual(to_household_date(result), date(2026, 8, 31))

    def test_it_anchors_to_the_start_of_the_day_not_the_end(self):
        """A reading must never look newer than it is — the safe direction
        for a staleness alert."""
        result = household_start_of_day(date(2026, 8, 31))

        self.assertEqual((result.hour, result.minute), (0, 0))

    def test_it_round_trips_through_to_household_date(self):
        for day in (date(2026, 1, 1), date(2026, 6, 15), date(2026, 12, 31)):
            with self.subTest(day=day):
                self.assertEqual(to_household_date(household_start_of_day(day)), day)

    def test_none_passes_through(self):
        self.assertIsNone(household_start_of_day(None))


class BudgetPeriodBoundaryTests(TestCase):
    def test_an_evening_purchase_lands_in_the_month_it_was_made(self):
        from decimal import Decimal

        budget = Budget.objects.create(
            name="Groceries", amount=Decimal("700"), anchor_date=date(2026, 1, 1)
        )

        with patch("finance.dates.timezone.now", return_value=LATE_EVENING):
            start, end = budget.period_for()

        # August, not September.
        self.assertEqual((start, end), (date(2026, 8, 1), date(2026, 8, 31)))
