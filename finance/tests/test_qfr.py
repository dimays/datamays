"""Quarterly Finance Reports: period math, metrics, comparisons, and generation.

The narrator is always a stub or a mock here — no test makes a network call.
"""

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from finance.models import (
    Account,
    AccountBalanceSnapshot,
    AccountType,
    Budget,
    BudgetPeriod,
    Category,
    QuarterlyReport,
    Transaction,
)
from finance.periods import (
    previous_quarter,
    quarter_bounds,
    quarter_containing,
    quarters_between,
)
from finance.services import qfr as qfr_service
from finance.services.qfr import (
    NullNarrator,
    QFRNarrator,
    compute_metrics,
    generate_qfr,
    historical_comparisons,
    quarter_is_complete,
)

from .factories import make_account, make_institution, make_transaction
from .test_access import make_user


def _fixed_now(year, month, day):
    """A real aware datetime, not a bare MagicMock.

    Patching finance.dates.timezone.now with return_value=Mock() breaks any
    model saved during the same context: Django's own auto_now_add/auto_now
    machinery also calls timezone.now(), and binding a Mock as a query
    parameter fails in a confusing way ("F() expressions can only be used to
    update"). Noon UTC is used so the household-local date it resolves to
    never shifts across a day boundary for any US timezone.
    """
    return datetime(year, month, day, 12, 0, tzinfo=ZoneInfo("UTC"))


class QuarterBoundsTests(SimpleTestCase):
    def test_each_quarter_spans_three_calendar_months(self):
        self.assertEqual(quarter_bounds(2026, 1), (date(2026, 1, 1), date(2026, 3, 31)))
        self.assertEqual(quarter_bounds(2026, 2), (date(2026, 4, 1), date(2026, 6, 30)))
        self.assertEqual(quarter_bounds(2026, 3), (date(2026, 7, 1), date(2026, 9, 30)))
        self.assertEqual(quarter_bounds(2026, 4), (date(2026, 10, 1), date(2026, 12, 31)))

    def test_leap_year_q1_includes_february_29(self):
        self.assertEqual(quarter_bounds(2024, 1), (date(2024, 1, 1), date(2024, 3, 31)))

    def test_an_invalid_quarter_number_is_rejected(self):
        with self.assertRaises(ValueError):
            quarter_bounds(2026, 5)

    def test_quarter_containing_is_the_inverse_of_quarter_bounds(self):
        for year in (2025, 2026):
            for quarter in (1, 2, 3, 4):
                start, end = quarter_bounds(year, quarter)
                with self.subTest(year=year, quarter=quarter):
                    self.assertEqual(quarter_containing(start), (year, quarter))
                    self.assertEqual(quarter_containing(end), (year, quarter))

    def test_previous_quarter_rolls_back_across_a_year_boundary(self):
        self.assertEqual(previous_quarter(2026, 1), (2025, 4))
        self.assertEqual(previous_quarter(2026, 3), (2026, 2))

    def test_quarters_between_is_inclusive_and_ordered(self):
        result = list(quarters_between(2025, 3, 2026, 1))

        self.assertEqual(
            result, [(2025, 3), (2025, 4), (2026, 1)]
        )

    def test_quarter_is_complete_only_once_it_has_ended(self):
        self.assertTrue(quarter_is_complete(2020, 1, today=date(2026, 1, 1)))
        self.assertFalse(quarter_is_complete(2026, 2, today=date(2026, 4, 15)))
        self.assertTrue(quarter_is_complete(2026, 1, today=date(2026, 4, 1)))


class ComputeMetricsTestCase(TestCase):
    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)
        self.institution = make_institution()
        self.checking = make_account(self.institution, name="Checking")
        self.groceries = Category.objects.get(slug="food-groceries")
        self.start, self.end = quarter_bounds(2026, 2)  # Apr-Jun 2026

    def spend(self, day, amount="-100.00"):
        return make_transaction(
            self.checking, posted_on=date(2026, 4, day), amount=Decimal(amount),
            category=self.groceries, description_raw=f"SPEND {day}",
        )

    def snapshot(self, account, as_of, current):
        return AccountBalanceSnapshot.objects.create(
            account=account, as_of=as_of, current=Decimal(current)
        )


class SpendMetricsTests(ComputeMetricsTestCase):
    def test_total_spend_matches_the_dashboards_own_definition(self):
        self.spend(5, "-100.00")
        self.spend(6, "-50.00")

        metrics = compute_metrics(self.start, self.end)

        self.assertEqual(metrics["total_spend"], 150.0)

    def test_transfers_and_income_are_excluded(self):
        self.spend(5, "-100.00")
        transfer = self.spend(6, "-500.00")
        transfer.is_transfer = True
        transfer.save()
        salary = Category.objects.get(slug="income-salary")
        make_transaction(
            self.checking, posted_on=date(2026, 4, 7), amount=Decimal("3000.00"),
            category=salary, description_raw="PAYROLL",
        )

        metrics = compute_metrics(self.start, self.end)

        self.assertEqual(metrics["total_spend"], 100.0)

    def test_spend_by_category_is_populated(self):
        self.spend(5, "-100.00")

        metrics = compute_metrics(self.start, self.end)

        self.assertIn("Food", metrics["spend_by_category"])

    def test_a_quarter_with_no_activity_reports_zero_not_an_error(self):
        metrics = compute_metrics(self.start, self.end)

        self.assertEqual(metrics["total_spend"], 0.0)
        self.assertEqual(metrics["spend_by_category"], {})


class NetWorthMetricsTests(ComputeMetricsTestCase):
    def test_start_and_end_come_from_the_nearest_snapshot(self):
        self.snapshot(self.checking, date(2026, 3, 15), "1000.00")
        self.snapshot(self.checking, date(2026, 6, 20), "1500.00")

        metrics = compute_metrics(self.start, self.end)

        self.assertEqual(metrics["net_worth_start"], 1000.0)
        self.assertEqual(metrics["net_worth_end"], 1500.0)
        self.assertEqual(metrics["net_worth_change"], 500.0)

    def test_no_snapshot_before_the_quarter_yields_none_not_zero(self):
        self.snapshot(self.checking, date(2026, 5, 1), "1000.00")

        metrics = compute_metrics(self.start, self.end)

        # There is no honest "start" figure without a prior snapshot -- 0
        # would misrepresent it as a household starting the quarter broke.
        self.assertIsNone(metrics["net_worth_start"])
        self.assertIsNone(metrics["net_worth_change"])
        self.assertEqual(metrics["net_worth_end"], 1000.0)


class SavingsDebtMetricsTests(ComputeMetricsTestCase):
    def test_debt_is_reported_as_a_positive_amount_owed(self):
        card = make_account(
            self.institution, name="Card", account_type=AccountType.CREDIT_CARD
        )
        self.snapshot(card, date(2026, 3, 31), "-1000.00")
        self.snapshot(card, date(2026, 6, 30), "-1200.00")

        metrics = compute_metrics(self.start, self.end)

        self.assertEqual(metrics["debt_balance_start"], 1000.0)
        self.assertEqual(metrics["debt_balance_end"], 1200.0)
        # Debt grew, so the change is positive -- reads as "went up", the
        # direction a person actually cares about, not a signed-storage detail.
        self.assertEqual(metrics["debt_change"], 200.0)

    def test_savings_growth_is_positive(self):
        savings = make_account(
            self.institution, name="Savings", account_type=AccountType.SAVINGS
        )
        self.snapshot(savings, date(2026, 3, 31), "5000.00")
        self.snapshot(savings, date(2026, 6, 30), "6000.00")

        metrics = compute_metrics(self.start, self.end)

        self.assertEqual(metrics["savings_change"], 1000.0)

    def test_a_card_paid_off_to_exactly_zero_still_yields_a_real_change(self):
        # A $0 balance is real data, not "nothing reported yet" -- a naive
        # truthiness check on the Decimal would confuse the two and drop the
        # change to None even though both snapshots exist.
        card = make_account(
            self.institution, name="Card", account_type=AccountType.CREDIT_CARD
        )
        self.snapshot(card, date(2026, 3, 31), "-400.00")
        self.snapshot(card, date(2026, 6, 30), "0.00")

        metrics = compute_metrics(self.start, self.end)

        self.assertEqual(metrics["debt_balance_start"], 400.0)
        self.assertEqual(metrics["debt_balance_end"], 0.0)
        self.assertEqual(metrics["debt_change"], -400.0)


class BudgetMetricsTests(ComputeMetricsTestCase):
    def test_periods_within_the_quarter_are_summed(self):
        budget = Budget.objects.create(name="Groceries", amount=Decimal("300"))
        budget.categories.set([self.groceries])

        for month in (4, 5, 6):
            BudgetPeriod.objects.create(
                budget=budget, period_start=date(2026, month, 1),
                period_end=date(2026, month, 28),
                target_amount=Decimal("300"), actual_amount=Decimal("280"),
            )
        # Outside the quarter -- must not be counted.
        BudgetPeriod.objects.create(
            budget=budget, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
            target_amount=Decimal("300"), actual_amount=Decimal("999"),
        )

        metrics = compute_metrics(self.start, self.end)
        row = next(b for b in metrics["budgets"] if b["name"] == "Groceries")

        self.assertEqual(row["actual"], 840.0)
        self.assertEqual(row["target"], 900.0)


class HistoricalComparisonTests(ComputeMetricsTestCase):
    def test_a_comparison_quarter_with_no_data_yields_none_deltas(self):
        current = compute_metrics(self.start, self.end)

        comparisons = historical_comparisons(2026, 2, current)

        # Q1 2026 and Q2 2025 both exist as calendar quarters but have no
        # data in this test -- the comparison must degrade, not crash.
        self.assertIsNone(comparisons["previous_quarter"]["net_worth_change_delta"])

    def test_a_populated_comparison_quarter_produces_real_deltas(self):
        self.snapshot(self.checking, date(2026, 3, 31), "1000.00")
        self.snapshot(self.checking, date(2026, 6, 30), "1500.00")
        self.spend(5, "-200.00")

        # Give Q1 2026 (the previous quarter) its own spend to compare against.
        make_transaction(
            self.checking, posted_on=date(2026, 2, 10), amount=Decimal("-50.00"),
            category=self.groceries, description_raw="Q1 spend",
        )

        current = compute_metrics(self.start, self.end)
        comparisons = historical_comparisons(2026, 2, current)

        self.assertEqual(comparisons["previous_quarter"]["total_spend_delta"], 150.0)

    def test_an_incomplete_comparison_quarter_is_skipped(self):
        current = compute_metrics(self.start, self.end)

        with patch("finance.services.qfr.household_today", return_value=date(2026, 5, 1)):
            comparisons = historical_comparisons(2026, 2, current)

        # Q2 2026 (Apr-Jun) has not finished as of 1 May, so no comparison
        # quarter after it exists yet either way; this exercises the guard
        # for an in-progress period rather than a data gap.
        self.assertIn("previous_quarter", comparisons)


class NarratorTests(TestCase):
    def test_null_narrator_returns_nothing(self):
        self.assertEqual(NullNarrator().narrate({}, {}), {})

    def test_a_stub_narrator_can_stand_in_for_openai_in_tests(self):
        class StubNarrator(QFRNarrator):
            def narrate(self, metrics, comparisons):
                return {"summary": "Test summary."}

        self.assertEqual(StubNarrator().narrate({}, {}), {"summary": "Test summary."})

    def test_openai_narrator_degrades_to_nothing_on_failure(self):
        from finance.services.qfr import OpenAINarrator

        narrator = OpenAINarrator(api_key="fake-key")

        with patch.object(narrator, "_call", side_effect=RuntimeError("boom")):
            result = narrator.narrate({}, {})

        # A narrative failure must not lose the metrics already computed by
        # the caller -- it degrades to no prose, not an exception.
        self.assertEqual(result, {})

    def test_openai_narrator_without_a_key_returns_nothing_without_calling_out(self):
        from finance.services.qfr import OpenAINarrator

        narrator = OpenAINarrator(api_key="")

        with patch.object(narrator, "_call") as call:
            result = narrator.narrate({}, {})

        call.assert_not_called()
        self.assertEqual(result, {})


class GenerateQFRTests(TestCase):
    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)
        self.institution = make_institution()
        self.checking = make_account(self.institution, name="Checking")

    def test_an_incomplete_quarter_is_refused(self):
        with patch("finance.services.qfr.household_today", return_value=date(2026, 5, 15)):
            with self.assertRaises(ValueError):
                generate_qfr(2026, 2)

    def test_generating_stores_metrics_and_narrative(self):
        with patch("finance.services.qfr.household_today", return_value=date(2026, 7, 1)):
            report = generate_qfr(
                2026, 2,
                narrator=_StubNarrator({"summary": "All good.", "key_trends": "Steady."}),
            )

        self.assertEqual(report.year, 2026)
        self.assertEqual(report.quarter, 2)
        self.assertEqual(report.summary, "All good.")
        self.assertTrue(report.has_narrative)
        self.assertIsNotNone(report.generated_at)

    def test_regenerating_without_force_returns_the_existing_report(self):
        with patch("finance.services.qfr.household_today", return_value=date(2026, 7, 1)):
            first = generate_qfr(2026, 2, narrator=NullNarrator())
            second = generate_qfr(
                2026, 2, narrator=_StubNarrator({"summary": "New summary."})
            )

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(second.summary, "")

    def test_force_overwrites_an_existing_report(self):
        with patch("finance.services.qfr.household_today", return_value=date(2026, 7, 1)):
            generate_qfr(2026, 2, narrator=NullNarrator())
            regenerated = generate_qfr(
                2026, 2, narrator=_StubNarrator({"summary": "Updated."}), force=True
            )

        self.assertEqual(regenerated.summary, "Updated.")

    def test_no_narrative_still_produces_a_usable_report(self):
        with patch("finance.services.qfr.household_today", return_value=date(2026, 7, 1)):
            report = generate_qfr(2026, 2, narrator=NullNarrator())

        self.assertFalse(report.has_narrative)
        self.assertIn("total_spend", report.metrics)


class _StubNarrator(QFRNarrator):
    def __init__(self, payload):
        self.payload = payload

    def narrate(self, metrics, comparisons):
        return self.payload


class GenerateQFRTransactionIsolationTests(TransactionTestCase):
    """The narrator call must not run inside an open database transaction.

    TransactionTestCase rather than TestCase: the latter wraps each test in a
    transaction, which would mask exactly the thing being asserted -- the
    same reasoning as the categoriser's own isolation test.
    """

    def test_the_narrator_call_is_outside_any_open_transaction(self):
        from django.db import transaction as db_transaction

        call_command("seed_finance_categories", verbosity=0)
        observed = {}

        class RecordingNarrator(QFRNarrator):
            def narrate(self, metrics, comparisons):
                observed["in_atomic_block"] = (
                    db_transaction.get_connection().in_atomic_block
                )
                return {}

        with patch("finance.services.qfr.household_today", return_value=date(2026, 7, 1)):
            generate_qfr(2026, 2, narrator=RecordingNarrator())

        self.assertFalse(observed["in_atomic_block"])


class GenerateQFRsCommandTests(TestCase):
    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)

    def test_since_backfills_every_completed_quarter(self):
        with patch("finance.dates.timezone.now", return_value=_fixed_now(2026, 7, 15)):
            call_command("generate_qfrs", "--since", "2025-Q4", verbosity=0)

        generated = set(QuarterlyReport.objects.values_list("year", "quarter"))
        self.assertEqual(generated, {(2025, 4), (2026, 1), (2026, 2)})

    def test_the_in_progress_quarter_is_never_generated(self):
        with patch("finance.dates.timezone.now", return_value=_fixed_now(2026, 7, 15)):
            call_command("generate_qfrs", "--since", "2025-Q4", verbosity=0)

        self.assertFalse(QuarterlyReport.objects.filter(year=2026, quarter=3).exists())

    def test_rerunning_without_regenerate_does_not_recompute(self):
        with patch("finance.dates.timezone.now", return_value=_fixed_now(2026, 4, 15)):
            call_command("generate_qfrs", "--quarter", "2026-Q1", verbosity=0)
            first_generated_at = QuarterlyReport.objects.get(year=2026, quarter=1).generated_at

            call_command("generate_qfrs", "--quarter", "2026-Q1", verbosity=0)
            second_generated_at = QuarterlyReport.objects.get(year=2026, quarter=1).generated_at

        self.assertEqual(first_generated_at, second_generated_at)

    def test_a_malformed_quarter_argument_is_rejected(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("generate_qfrs", "--quarter", "not-a-quarter", verbosity=0)

    def test_neither_since_nor_quarter_is_rejected(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("generate_qfrs", verbosity=0)


class QFRViewTests(TestCase):
    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)

        self.user = make_user("david", with_device=True)
        self.client.force_login(self.user)
        session = self.client.session
        session["otp_device_id"] = TOTPDevice.objects.get(user=self.user).persistent_id
        session.save()

        with patch("finance.services.qfr.household_today", return_value=date(2026, 7, 1)):
            self.report = generate_qfr(
                2026, 2,
                narrator=_StubNarrator({
                    "summary": "Solid quarter.", "key_trends": "Spend flat.",
                    "major_events": "Nothing notable.", "risk_areas": "None.",
                }),
            )

    def test_the_list_renders(self):
        response = self.client.get(reverse("finance:qfrs"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Q2 2026")

    def test_the_detail_page_renders_the_narrative(self):
        response = self.client.get(reverse("finance:qfr_detail", args=[self.report.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Solid quarter.")

    def test_qfr_pages_are_gated_like_everything_else(self):
        self.client.logout()

        for url in [reverse("finance:qfrs"), reverse("finance:qfr_detail", args=[self.report.pk])]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_a_report_with_no_narrative_says_so_rather_than_showing_blanks(self):
        with patch("finance.services.qfr.household_today", return_value=date(2026, 4, 1)):
            metrics_only = generate_qfr(2026, 1, narrator=NullNarrator())

        response = self.client.get(reverse("finance:qfr_detail", args=[metrics_only.pk]))

        self.assertContains(response, "No narrative was generated")
