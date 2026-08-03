from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from finance.models import (
    Account,
    AccountType,
    Budget,
    BudgetPeriod,
    Category,
    CategoryKind,
    CategoryRule,
    DeductionKind,
    MatchType,
    Paycheck,
    PaycheckDeduction,
    Transaction,
    build_fingerprint,
)

from .factories import (
    make_account,
    make_category,
    make_institution,
    make_transaction,
    make_user,
)


class SignConventionTests(TestCase):
    """Assets positive, liabilities negative — so balances sum to net worth."""

    def test_liability_types_are_recognised(self):
        card = make_account(account_type=AccountType.CREDIT_CARD, name="Chase card")
        checking = make_account(account_type=AccountType.CHECKING, name="Checking")

        self.assertTrue(card.is_liability)
        self.assertFalse(checking.is_liability)

    def test_balances_sum_directly_to_net_worth(self):
        institution = make_institution()
        make_account(institution, name="Checking", current_balance=Decimal("4200.00"))
        make_account(
            institution,
            name="Card",
            account_type=AccountType.CREDIT_CARD,
            current_balance=Decimal("-1350.00"),
        )
        make_account(
            institution,
            name="Mortgage",
            account_type=AccountType.MORTGAGE,
            current_balance=Decimal("-289000.00"),
        )

        net_worth = sum(a.current_balance for a in Account.objects.all())

        self.assertEqual(net_worth, Decimal("-286150.00"))

    def test_display_balance_reads_a_debt_as_positive(self):
        card = make_account(
            account_type=AccountType.CREDIT_CARD, current_balance=Decimal("-1350.00")
        )
        checking = make_account(
            name="Checking", current_balance=Decimal("4200.00")
        )

        self.assertEqual(card.display_balance, Decimal("1350.00"))
        self.assertEqual(checking.display_balance, Decimal("4200.00"))

    def test_high_frequency_classification_drives_sync_cadence(self):
        self.assertTrue(make_account(account_type=AccountType.CHECKING).is_high_frequency)
        self.assertFalse(make_account(account_type=AccountType.MORTGAGE, name="M").is_high_frequency)


class TransactionIdentityTests(TestCase):
    def test_fingerprint_is_stable_for_the_same_transaction(self):
        args = dict(
            account_id=1,
            posted_on=date(2026, 4, 15),
            amount=Decimal("-42.50"),
            description="MARIANOS #1234",
        )

        self.assertEqual(build_fingerprint(**args), build_fingerprint(**args))

    def test_fingerprint_ignores_case_and_surrounding_whitespace(self):
        base = dict(account_id=1, posted_on=date(2026, 4, 15), amount=Decimal("-42.50"))

        self.assertEqual(
            build_fingerprint(**base, description="  Marianos #1234 "),
            build_fingerprint(**base, description="MARIANOS #1234"),
        )

    def test_sequence_distinguishes_genuine_repeats(self):
        # Two identical coffees on one day are two transactions, not one.
        base = dict(
            account_id=1,
            posted_on=date(2026, 4, 15),
            amount=Decimal("-4.75"),
            description="STARBUCKS",
        )

        self.assertNotEqual(
            build_fingerprint(**base, sequence=0), build_fingerprint(**base, sequence=1)
        )

    def test_reimporting_the_same_row_is_rejected(self):
        account = make_account()
        make_transaction(account)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_transaction(account)

    def test_the_same_provider_id_cannot_land_twice(self):
        account = make_account()
        make_transaction(account, provider_txn_id="sf-001")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_transaction(
                    account, provider_txn_id="sf-001", amount=Decimal("-99.00")
                )

    def test_blank_provider_ids_do_not_collide(self):
        # Every CSV row has an empty provider ID; they must not conflict.
        account = make_account()
        make_transaction(account, amount=Decimal("-1.00"))
        make_transaction(account, amount=Decimal("-2.00"))

        self.assertEqual(Transaction.objects.count(), 2)

    def test_same_transaction_on_two_accounts_is_allowed(self):
        institution = make_institution()
        first = make_account(institution, name="A")
        second = make_account(institution, name="B")

        make_transaction(first)
        make_transaction(second)

        self.assertEqual(Transaction.objects.count(), 2)


class CategoryTests(TestCase):
    def test_full_path_reads_top_down(self):
        food = make_category(name="Food", slug="food")
        groceries = make_category(name="Groceries", slug="groceries", parent=food)

        self.assertEqual(groceries.full_path, "Food › Groceries")
        self.assertEqual(groceries.depth, 2)

    def test_nesting_is_capped(self):
        one = make_category(name="One", slug="one")
        two = make_category(name="Two", slug="two", parent=one)
        three = make_category(name="Three", slug="three", parent=two)

        too_deep = Category(name="Four", slug="four", parent=three, kind=CategoryKind.EXPENSE)

        with self.assertRaises(ValidationError):
            too_deep.full_clean()

    def test_a_subcategory_cannot_change_kind(self):
        income = make_category(name="Income", slug="income", kind=CategoryKind.INCOME)
        child = Category(name="Groceries", slug="g", parent=income, kind=CategoryKind.EXPENSE)

        with self.assertRaises(ValidationError):
            child.full_clean()


class CategoryRuleTests(TestCase):
    def setUp(self):
        self.category = make_category()
        self.account = make_account()

    def rule(self, **kwargs):
        kwargs.setdefault("pattern", "marianos")
        kwargs.setdefault("category", self.category)
        return CategoryRule(**kwargs)

    def test_contains_is_case_insensitive(self):
        self.assertTrue(
            self.rule().matches(description="MARIANOS #1234", amount=Decimal("-40"))
        )

    def test_non_matching_description_is_rejected(self):
        self.assertFalse(
            self.rule().matches(description="JEWEL OSCO", amount=Decimal("-40"))
        )

    def test_inactive_rules_never_match(self):
        self.assertFalse(
            self.rule(is_active=False).matches(
                description="MARIANOS", amount=Decimal("-40")
            )
        )

    def test_account_scoped_rule_ignores_other_accounts(self):
        scoped = self.rule(account=self.account)

        self.assertTrue(
            scoped.matches(
                description="MARIANOS", amount=Decimal("-40"), account_id=self.account.id
            )
        )
        self.assertFalse(
            scoped.matches(
                description="MARIANOS", amount=Decimal("-40"), account_id=self.account.id + 1
            )
        )

    def test_amount_bounds_are_inclusive_and_signed(self):
        bounded = self.rule(min_amount=Decimal("-100"), max_amount=Decimal("-10"))

        self.assertTrue(bounded.matches(description="MARIANOS", amount=Decimal("-100")))
        self.assertTrue(bounded.matches(description="MARIANOS", amount=Decimal("-10")))
        self.assertFalse(bounded.matches(description="MARIANOS", amount=Decimal("-5")))
        self.assertFalse(bounded.matches(description="MARIANOS", amount=Decimal("-200")))

    def test_regex_matching(self):
        regex = self.rule(pattern=r"^AMZN\s+MKTP", match_type=MatchType.REGEX)

        self.assertTrue(regex.matches(description="AMZN  MKTP US*2X4", amount=Decimal("-20")))
        self.assertFalse(regex.matches(description="PAY AMZN MKTP", amount=Decimal("-20")))

    def test_invalid_regex_is_caught_at_validation(self):
        bad = self.rule(pattern="[unclosed", match_type=MatchType.REGEX)

        with self.assertRaises(ValidationError):
            bad.full_clean()

    def test_inverted_amount_bounds_are_rejected(self):
        with self.assertRaises(ValidationError):
            self.rule(min_amount=Decimal("10"), max_amount=Decimal("-10")).full_clean()


class BudgetTests(TestCase):
    def test_period_follows_the_anchor(self):
        budget = Budget.objects.create(
            name="Groceries", amount=Decimal("800"), anchor_date=date(2026, 1, 15)
        )

        self.assertEqual(
            budget.period_for(date(2026, 3, 2)), (date(2026, 2, 15), date(2026, 3, 14))
        )

    def test_attainment_and_remaining(self):
        budget = Budget.objects.create(name="Groceries", amount=Decimal("800"))
        period = BudgetPeriod.objects.create(
            budget=budget,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
            target_amount=Decimal("800"),
            actual_amount=Decimal("600"),
        )

        self.assertEqual(period.remaining, Decimal("200"))
        self.assertAlmostEqual(period.attainment, 0.75)
        self.assertFalse(period.is_over)

    def test_attainment_is_none_for_a_zero_target(self):
        budget = Budget.objects.create(name="Zero", amount=Decimal("0"))
        period = BudgetPeriod.objects.create(
            budget=budget,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
            target_amount=Decimal("0"),
        )

        self.assertIsNone(period.attainment)

    def test_pace_difference_flags_spending_too_fast(self):
        budget = Budget.objects.create(name="Groceries", amount=Decimal("800"))
        period = BudgetPeriod.objects.create(
            budget=budget,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
            target_amount=Decimal("800"),
            actual_amount=Decimal("600"),
        )

        # A third of the way in: an even pace predicts ~$267, so $600 is hot.
        hot = period.pace_difference(date(2026, 4, 10))
        self.assertGreater(hot, Decimal("300"))

        # By the 30th the same spend is comfortably under.
        cool = period.pace_difference(date(2026, 4, 30))
        self.assertEqual(cool, Decimal("-200.00"))


class PaycheckTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def make_paycheck(self, gross="5000.00", net="3400.00"):
        return Paycheck.objects.create(
            user=self.user,
            employer="Acme",
            pay_date=date(2026, 4, 15),
            gross=Decimal(gross),
            net=Decimal(net),
        )

    def test_deductions_reconcile_gross_to_net(self):
        paycheck = self.make_paycheck()

        for kind, amount in [
            (DeductionKind.FEDERAL_TAX, "800.00"),
            (DeductionKind.STATE_TAX, "250.00"),
            (DeductionKind.FICA, "350.00"),
            (DeductionKind.RETIREMENT, "200.00"),
        ]:
            PaycheckDeduction.objects.create(
                paycheck=paycheck, kind=kind, amount=Decimal(amount)
            )

        self.assertEqual(paycheck.total_deductions, Decimal("1600.00"))
        self.assertTrue(paycheck.reconciles)

    def test_a_missed_payslip_line_is_detected(self):
        paycheck = self.make_paycheck()
        PaycheckDeduction.objects.create(
            paycheck=paycheck,
            kind=DeductionKind.FEDERAL_TAX,
            amount=Decimal("800.00"),
        )

        self.assertFalse(paycheck.reconciles)

    def test_retirement_and_hsa_count_as_retained(self):
        paycheck = self.make_paycheck()

        for kind, amount in [
            (DeductionKind.RETIREMENT, "200.00"),
            (DeductionKind.HSA, "100.00"),
            (DeductionKind.FEDERAL_TAX, "800.00"),
        ]:
            PaycheckDeduction.objects.create(
                paycheck=paycheck, kind=kind, amount=Decimal(amount)
            )

        # Retirement and HSA are still household money; tax is not.
        self.assertEqual(paycheck.retained_deductions, Decimal("300.00"))

    def test_the_same_paycheck_cannot_be_imported_twice(self):
        self.make_paycheck()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.make_paycheck(net="9999.00")
