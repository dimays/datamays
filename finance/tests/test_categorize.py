"""The categorization pipeline.

The classifier is always a stub here — no test makes a network call.
"""

from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase, TransactionTestCase

from finance.categories_seed import CARD_PAYMENT_SLUG, TRANSFER_SLUG, UNCATEGORIZED_SLUG
from finance.models import (
    AccountType,
    Category,
    CategoryRule,
    CategorySource,
    MatchType,
    MerchantCategoryMemo,
    Transaction,
)
from finance.services.categorize import (
    REVIEW_THRESHOLD,
    categorize_transactions,
    confirm_category,
    find_transfer_pairs,
)
from finance.services.classifier import Classification, Classifier
from finance.services.merchants import normalize_merchant

from .factories import make_account, make_institution, make_transaction, make_user


class StubClassifier(Classifier):
    """Returns canned answers and records what it was asked."""

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.calls = []

    def classify(self, merchant_keys, categories):
        self.calls.append(list(merchant_keys))

        return [
            Classification(merchant_key=key, category_slug=slug, confidence=confidence)
            for key, (slug, confidence) in self.answers.items()
            if key in merchant_keys
        ]


class MerchantNormalizationTests(TestCase):
    def test_store_numbers_and_locations_collapse_to_one_key(self):
        first = normalize_merchant("SQ *BLUE BOTTLE COFFEE 4471 CHICAGO IL 04/15")
        second = normalize_merchant("SQ *BLUE BOTTLE COFFEE 9920 EVANSTON IL 05/02")

        self.assertEqual(first, second)
        self.assertIn("blue bottle", first)

    def test_processor_prefixes_are_stripped(self):
        self.assertEqual(
            normalize_merchant("TST* MARIANOS"), normalize_merchant("MARIANOS")
        )

    def test_card_masks_and_reference_numbers_are_removed(self):
        key = normalize_merchant("AMAZON.COM*XX1234 REF:99A8B7")
        self.assertNotIn("1234", key)
        self.assertIn("amazon", key)

    def test_different_merchants_stay_different(self):
        self.assertNotEqual(
            normalize_merchant("MARIANOS #1234"), normalize_merchant("JEWEL OSCO #99")
        )

    def test_unusable_descriptions_yield_an_empty_key(self):
        for value in ["", "   ", "12345", None]:
            with self.subTest(value=value):
                self.assertEqual(normalize_merchant(value), "")


class PipelineTestCase(TestCase):
    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)
        self.institution = make_institution()
        self.checking = make_account(self.institution, name="Checking")
        self.groceries = Category.objects.get(slug="food-groceries")
        self.coffee = Category.objects.get(slug="food-coffee")


class RuleTests(PipelineTestCase):
    def test_a_rule_wins_and_is_fully_confident(self):
        CategoryRule.objects.create(pattern="marianos", category=self.groceries)
        txn = make_transaction(self.checking, description_raw="MARIANOS #1234 CHICAGO IL")

        categorize_transactions(classifier=StubClassifier())

        txn.refresh_from_db()
        self.assertEqual(txn.category, self.groceries)
        self.assertEqual(txn.category_source, CategorySource.RULE)
        self.assertEqual(txn.category_confidence, 1.0)
        self.assertFalse(txn.needs_review)

    def test_a_rule_beats_the_classifier(self):
        CategoryRule.objects.create(pattern="marianos", category=self.groceries)
        txn = make_transaction(self.checking, description_raw="MARIANOS #1234")

        classifier = StubClassifier({"marianos": ("food-restaurants", 0.99)})
        categorize_transactions(classifier=classifier)

        txn.refresh_from_db()
        self.assertEqual(txn.category, self.groceries)
        # And the classifier was never even asked about it.
        self.assertEqual(classifier.calls, [])

    def test_priority_decides_between_competing_rules(self):
        CategoryRule.objects.create(pattern="coffee", category=self.coffee, priority=10)
        CategoryRule.objects.create(pattern="coffee", category=self.groceries, priority=50)

        txn = make_transaction(self.checking, description_raw="BLUE BOTTLE COFFEE")
        categorize_transactions(classifier=StubClassifier())

        txn.refresh_from_db()
        self.assertEqual(txn.category, self.coffee)


class MemoTests(PipelineTestCase):
    def test_a_remembered_merchant_skips_the_classifier(self):
        MerchantCategoryMemo.objects.create(
            merchant_key=normalize_merchant("MARIANOS #1234"), category=self.groceries
        )
        txn = make_transaction(self.checking, description_raw="MARIANOS #5678 CHICAGO IL")

        classifier = StubClassifier()
        categorize_transactions(classifier=classifier)

        txn.refresh_from_db()
        self.assertEqual(txn.category, self.groceries)
        self.assertEqual(txn.category_source, CategorySource.MEMO)
        self.assertEqual(classifier.calls, [])

    def test_memo_hit_counts_are_tracked(self):
        memo = MerchantCategoryMemo.objects.create(
            merchant_key=normalize_merchant("MARIANOS"), category=self.groceries
        )
        make_transaction(self.checking, description_raw="MARIANOS #1")

        categorize_transactions(classifier=StubClassifier())

        memo.refresh_from_db()
        self.assertEqual(memo.hit_count, 1)
        self.assertIsNotNone(memo.last_used_at)


class ClassifierTests(PipelineTestCase):
    def test_a_confident_classification_is_applied_and_remembered(self):
        txn = make_transaction(self.checking, description_raw="BLUE BOTTLE COFFEE 4471")
        key = normalize_merchant(txn.description_raw)

        categorize_transactions(classifier=StubClassifier({key: ("food-coffee", 0.95)}))

        txn.refresh_from_db()
        self.assertEqual(txn.category, self.coffee)
        self.assertEqual(txn.category_source, CategorySource.LLM)
        self.assertFalse(txn.needs_review)
        self.assertTrue(MerchantCategoryMemo.objects.filter(merchant_key=key).exists())

    def test_a_shaky_classification_is_flagged_and_not_remembered(self):
        txn = make_transaction(self.checking, description_raw="ACME HOLDINGS LLC")
        key = normalize_merchant(txn.description_raw)

        categorize_transactions(
            classifier=StubClassifier({key: ("food-coffee", REVIEW_THRESHOLD - 0.2)})
        )

        txn.refresh_from_db()
        self.assertTrue(txn.needs_review)
        # Remembering a guess would silently propagate it forever.
        self.assertFalse(MerchantCategoryMemo.objects.filter(merchant_key=key).exists())

    def test_the_classifier_is_asked_once_per_merchant_not_per_transaction(self):
        for day in range(1, 6):
            make_transaction(
                self.checking,
                posted_on=date(2026, 4, day),
                amount=Decimal(f"-{day}.75"),
                description_raw=f"BLUE BOTTLE COFFEE 447{day}",
            )

        classifier = StubClassifier()
        categorize_transactions(classifier=classifier)

        self.assertEqual(len(classifier.calls), 1)
        self.assertEqual(len(classifier.calls[0]), 1)

    def test_unclassified_transactions_land_in_the_review_queue(self):
        txn = make_transaction(self.checking, description_raw="MYSTERY VENDOR XYZ")

        categorize_transactions(classifier=StubClassifier())

        txn.refresh_from_db()
        self.assertEqual(txn.category.slug, UNCATEGORIZED_SLUG)
        self.assertTrue(txn.needs_review)

    def test_a_hallucinated_slug_is_discarded_rather_than_applied(self):
        from finance.services.classifier import OpenAIClassifier

        parsed = list(
            OpenAIClassifier(api_key="x")._parse(
                {"results": [{"merchant": "acme", "category": "not-a-real-slug", "confidence": 0.99}]},
                ["acme"],
                {"food-groceries"},
            )
        )

        self.assertEqual(parsed, [])

    def test_a_merchant_we_never_asked_about_is_discarded(self):
        from finance.services.classifier import OpenAIClassifier

        parsed = list(
            OpenAIClassifier(api_key="x")._parse(
                {"results": [{"merchant": "someone else", "category": "food-groceries", "confidence": 0.99}]},
                ["acme"],
                {"food-groceries"},
            )
        )

        self.assertEqual(parsed, [])

    def test_the_system_prompt_says_json_as_required_by_response_format(self):
        # OpenAI's API rejects response_format=json_object unless one of the
        # messages literally contains the word "json" — a 400 that silently
        # failed every batch in production until this was added.
        from finance.services.classifier import SYSTEM_PROMPT

        self.assertIn("json", SYSTEM_PROMPT.lower())

    def test_the_system_prompt_insists_on_a_verbatim_slug_copy(self):
        # A production run classified real merchants and the model invented
        # plausible-but-nonexistent slugs (e.g. "transport-auto-maintenance"
        # instead of "transport-maintenance") often enough to be worth
        # explicitly warning against, even though _parse's allowed-slug guard
        # already discards anything that doesn't match.
        from finance.services.classifier import SYSTEM_PROMPT

        self.assertIn("character-for-character", SYSTEM_PROMPT)

    def test_without_an_api_key_the_deterministic_steps_still_work(self):
        from finance.services.classifier import NullClassifier

        CategoryRule.objects.create(pattern="marianos", category=self.groceries)
        ruled = make_transaction(self.checking, description_raw="MARIANOS #1")
        unknown = make_transaction(
            self.checking, description_raw="MYSTERY LLC", amount=Decimal("-9.00")
        )

        categorize_transactions(classifier=NullClassifier())

        ruled.refresh_from_db()
        unknown.refresh_from_db()

        self.assertEqual(ruled.category, self.groceries)
        self.assertTrue(unknown.needs_review)


class TransferTests(PipelineTestCase):
    def setUp(self):
        super().setUp()
        self.savings = make_account(
            self.institution, name="Savings", account_type=AccountType.SAVINGS
        )
        self.card = make_account(
            self.institution, name="Card", account_type=AccountType.CREDIT_CARD
        )

    def test_matched_opposite_legs_are_paired(self):
        out = make_transaction(
            self.checking, amount=Decimal("-500.00"), description_raw="TRANSFER TO SAVINGS"
        )
        into = make_transaction(
            self.savings, amount=Decimal("500.00"), description_raw="TRANSFER FROM CHECKING"
        )

        self.assertEqual(find_transfer_pairs(), 1)

        out.refresh_from_db()
        into.refresh_from_db()

        self.assertTrue(out.is_transfer)
        self.assertTrue(into.is_transfer)
        self.assertEqual(out.transfer_pair, into)
        self.assertEqual(out.category.slug, TRANSFER_SLUG)

    def test_legs_posting_days_apart_still_pair(self):
        make_transaction(
            self.checking, posted_on=date(2026, 4, 15), amount=Decimal("-500.00")
        )
        make_transaction(
            self.savings, posted_on=date(2026, 4, 17), amount=Decimal("500.00")
        )

        self.assertEqual(find_transfer_pairs(), 1)

    def test_legs_too_far_apart_are_not_paired(self):
        make_transaction(
            self.checking, posted_on=date(2026, 4, 1), amount=Decimal("-500.00")
        )
        make_transaction(
            self.savings, posted_on=date(2026, 4, 30), amount=Decimal("500.00")
        )

        self.assertEqual(find_transfer_pairs(), 0)

    def test_a_card_payment_gets_its_own_category(self):
        make_transaction(
            self.checking, amount=Decimal("-1350.00"), description_raw="CHASE CARD PAYMENT"
        )
        make_transaction(
            self.card, amount=Decimal("1350.00"), description_raw="PAYMENT THANK YOU"
        )

        find_transfer_pairs()

        payment = Transaction.objects.get(account=self.checking)
        self.assertEqual(payment.category.slug, CARD_PAYMENT_SLUG)

    def test_two_unrelated_amounts_on_one_account_are_not_paired(self):
        # Same account, so this is a purchase and a refund, not a transfer.
        make_transaction(self.checking, amount=Decimal("-50.00"), description_raw="SHOP")
        make_transaction(
            self.checking,
            amount=Decimal("50.00"),
            description_raw="SHOP REFUND",
            posted_on=date(2026, 4, 16),
        )

        self.assertEqual(find_transfer_pairs(), 0)

    def test_transfers_are_excluded_from_the_classifier(self):
        make_transaction(self.checking, amount=Decimal("-500.00"))
        make_transaction(self.savings, amount=Decimal("500.00"))

        classifier = StubClassifier()
        summary = categorize_transactions(classifier=classifier)

        self.assertEqual(summary.transfers, 1)
        self.assertEqual(classifier.calls, [])


class ConfirmationTests(PipelineTestCase):
    def test_confirming_records_a_memo_so_it_is_never_asked_again(self):
        user = make_user()
        txn = make_transaction(self.checking, description_raw="BLUE BOTTLE COFFEE 4471")

        confirm_category(txn, self.coffee, user)

        txn.refresh_from_db()
        self.assertEqual(txn.category_source, CategorySource.MANUAL)
        self.assertFalse(txn.needs_review)

        memo = MerchantCategoryMemo.objects.get(
            merchant_key=normalize_merchant("BLUE BOTTLE COFFEE 4471")
        )
        self.assertEqual(memo.category, self.coffee)
        self.assertEqual(memo.confirmed_by, user)

    def test_a_confirmed_merchant_categorizes_future_transactions_automatically(self):
        first = make_transaction(self.checking, description_raw="BLUE BOTTLE COFFEE 4471")
        confirm_category(first, self.coffee)

        later = make_transaction(
            self.checking,
            posted_on=date(2026, 5, 2),
            amount=Decimal("-5.25"),
            description_raw="SQ *BLUE BOTTLE COFFEE 9920 EVANSTON IL",
        )

        classifier = StubClassifier()
        categorize_transactions(classifier=classifier)

        later.refresh_from_db()
        self.assertEqual(later.category, self.coffee)
        self.assertEqual(classifier.calls, [])

    def test_a_manual_choice_is_never_overwritten_by_a_rerun(self):
        txn = make_transaction(self.checking, description_raw="MARIANOS #1234")
        confirm_category(txn, self.coffee, remember=False)

        CategoryRule.objects.create(pattern="marianos", category=self.groceries)
        categorize_transactions(classifier=StubClassifier())

        txn.refresh_from_db()
        self.assertEqual(txn.category, self.coffee)


class ClassifierIsolationTests(TransactionTestCase):
    """The provider call must not run inside an open database transaction.

    TransactionTestCase rather than TestCase: the latter wraps each test in a
    transaction, which would mask exactly the thing being asserted.
    """

    def test_categorization_does_not_hold_a_transaction_across_the_call(self):
        from django.db import transaction as db_transaction

        call_command("seed_finance_categories", verbosity=0)
        account = make_account(make_institution(), name="Checking")
        make_transaction(account, description_raw="MYSTERY VENDOR LLC")

        observed = {}

        class RecordingClassifier(Classifier):
            def classify(self, merchant_keys, categories):
                observed["in_atomic_block"] = (
                    db_transaction.get_connection().in_atomic_block
                )
                return []

        categorize_transactions(classifier=RecordingClassifier())

        # A held transaction pins a database connection for as long as the
        # provider takes to answer.
        self.assertFalse(observed["in_atomic_block"])

    def test_the_provider_client_sets_a_timeout(self):
        from finance.services.classifier import REQUEST_TIMEOUT_SECONDS

        # An unbounded wait would stall every later step in the hourly chain.
        self.assertGreater(REQUEST_TIMEOUT_SECONDS, 0)
        self.assertLessEqual(REQUEST_TIMEOUT_SECONDS, 120)


class ReviewQueueRedirectTests(PipelineTestCase):
    def test_confirming_a_category_cannot_bounce_off_site(self):
        from django.urls import reverse
        from django_otp.plugins.otp_totp.models import TOTPDevice

        from .test_access import make_user

        user = make_user("david", with_device=True)
        self.client.force_login(user)
        session = self.client.session
        session["otp_device_id"] = TOTPDevice.objects.get(user=user).persistent_id
        session.save()

        txn = make_transaction(self.checking)

        response = self.client.post(
            reverse("finance:transactions"),
            {
                "transaction": txn.pk,
                "category": self.groceries.pk,
                "next": "//evil.example.com/steal",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/"))
        self.assertNotIn("evil.example.com", response["Location"])
