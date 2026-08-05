"""Assigning a category to a transaction.

Four steps, cheapest and most certain first. The LLM is the last resort, not
the default:

1. **Transfer detection** — money moved between our own accounts is neither
   spend nor income, and mislabelling it double-counts everything.
2. **Rules** — the household's own deterministic mappings. These always win,
   so the categories that matter most are never at the mercy of a model.
3. **Merchant memos** — a decision already confirmed for this merchant.
   Recurring merchants are most of a household's activity, so this absorbs
   the overwhelming majority of transactions and is why the LLM stays cheap.
4. **Classifier** — genuinely new merchants only.

Anything the classifier is unsure about is flagged for review rather than
quietly accepted. Confirming a review writes a memo, so the same merchant is
never asked about twice.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from ..categories_seed import CARD_PAYMENT_SLUG, TRANSFER_SLUG, UNCATEGORIZED_SLUG
from ..models import (
    LIABILITY_TYPES,
    Category,
    CategoryRule,
    CategorySource,
    MerchantCategoryMemo,
    Transaction,
)
from .classifier import get_classifier
from .merchants import normalise_merchant

logger = logging.getLogger(__name__)

# Below this, a classification is applied but flagged for a human to confirm.
REVIEW_THRESHOLD = 0.75

# How far apart the two legs of a transfer may post and still be paired.
TRANSFER_WINDOW_DAYS = 4


@dataclass
class CategorizationSummary:
    transfers: int = 0
    by_rule: int = 0
    by_memo: int = 0
    by_classifier: int = 0
    needs_review: int = 0
    unmatched: int = 0


def find_transfer_pairs(transactions=None):
    """Pair equal-and-opposite movements between the household's own accounts.

    Without this, moving $500 from checking to savings reads as $500 of
    spending and $500 of income in the same month, which corrupts every
    number on the spend and income dashboards.
    """
    queryset = transactions if transactions is not None else Transaction.objects.filter(
        is_transfer=False, transfer_pair__isnull=True
    )

    paired = 0

    for candidate in queryset.filter(amount__lt=0).select_related("account"):
        if candidate.transfer_pair_id or candidate.is_transfer:
            continue

        window_start = candidate.posted_on - timedelta(days=TRANSFER_WINDOW_DAYS)
        window_end = candidate.posted_on + timedelta(days=TRANSFER_WINDOW_DAYS)

        match = (
            Transaction.objects.filter(
                amount=-candidate.amount,
                posted_on__range=(window_start, window_end),
                transfer_pair__isnull=True,
            )
            .exclude(account_id=candidate.account_id)
            .exclude(pk=candidate.pk)
            .select_related("account")
            .first()
        )

        if match is None:
            continue

        # Paying a credit card is a transfer too, but worth its own category
        # so it can be told apart from moving cash into savings.
        slug = (
            CARD_PAYMENT_SLUG
            if match.account.account_type in LIABILITY_TYPES
            else TRANSFER_SLUG
        )
        category = Category.objects.filter(slug=slug).first()

        for leg, other in ((candidate, match), (match, candidate)):
            leg.is_transfer = True
            leg.transfer_pair = other
            leg.category = category
            leg.category_source = CategorySource.TRANSFER
            leg.category_confidence = 1.0
            leg.needs_review = False
            leg.save(
                update_fields=[
                    "is_transfer", "transfer_pair", "category",
                    "category_source", "category_confidence", "needs_review",
                    "updated_at",
                ]
            )

        paired += 1

    return paired


def apply_rules(transaction, rules):
    """First matching rule wins; rules are ordered by priority."""
    for rule in rules:
        if rule.matches(
            description=transaction.description_raw,
            amount=transaction.amount,
            account_id=transaction.account_id,
        ):
            return rule.category

    return None


def category_catalogue():
    """The category list handed to the classifier.

    Only leaves are offered: a parent like "Food" is never the right answer
    when "Groceries" and "Restaurants" exist, and offering both invites
    inconsistency.
    """
    return [
        {
            "slug": category.slug,
            "name": category.full_path,
            "description": category.description,
        }
        for category in Category.objects.filter(
            is_active=True, children__isnull=True
        ).select_related("parent")
    ]


def remember_merchant(merchant_key, category, user=None):
    """Record a confirmed decision so this merchant is never asked about again."""
    if not merchant_key:
        return None

    memo, _ = MerchantCategoryMemo.objects.update_or_create(
        merchant_key=merchant_key,
        defaults={"category": category, "confirmed_by": user},
    )

    return memo


def categorize_transactions(queryset=None, *, classifier=None, detect_transfers=True):
    """Run the pipeline over uncategorized transactions.

    Deliberately not wrapped in a single transaction. The classifier step makes
    a network call, and holding a database transaction open across it would pin
    a connection for as long as the provider takes to answer — on a small
    Postgres plan that is a real availability risk.
    """
    summary = CategorizationSummary()

    if detect_transfers:
        summary.transfers = find_transfer_pairs()

    pending = (
        queryset
        if queryset is not None
        else Transaction.objects.filter(category__isnull=True, is_transfer=False)
    ).select_related("account")

    rules = list(CategoryRule.objects.filter(is_active=True).select_related("category"))
    memos = {
        memo.merchant_key: memo
        for memo in MerchantCategoryMemo.objects.select_related("category")
    }

    awaiting_classifier = {}

    for txn in pending:
        if txn.is_transfer:
            continue

        rule_category = apply_rules(txn, rules)

        if rule_category is not None:
            _assign(txn, rule_category, CategorySource.RULE, 1.0)
            summary.by_rule += 1
            continue

        merchant_key = normalise_merchant(txn.description_raw)

        if merchant_key and merchant_key in memos:
            memo = memos[merchant_key]
            _assign(txn, memo.category, CategorySource.MEMO, 1.0)

            memo.hit_count += 1
            memo.last_used_at = timezone.now()
            memo.save(update_fields=["hit_count", "last_used_at", "updated_at"])

            summary.by_memo += 1
            continue

        if merchant_key:
            awaiting_classifier.setdefault(merchant_key, []).append(txn)
        else:
            _assign_uncategorized(txn)
            summary.unmatched += 1

    if awaiting_classifier:
        summary = _run_classifier(awaiting_classifier, classifier, summary)

    return summary


def _run_classifier(awaiting, classifier, summary):
    classifier = classifier or get_classifier()
    catalogue = category_catalogue()

    # One entry per distinct merchant, not per transaction — forty coffees
    # from one shop cost one line in one request.
    merchant_keys = sorted(awaiting)

    # Outside any transaction: this is a network call to a third party.
    results = classifier.classify(merchant_keys, catalogue)

    by_slug = {
        category.slug: category
        for category in Category.objects.filter(
            slug__in={result.category_slug for result in results}
        )
    }

    classified = set()

    for result in results:
        category = by_slug.get(result.category_slug)

        if category is None:
            continue

        needs_review = result.confidence < REVIEW_THRESHOLD

        for txn in awaiting.get(result.merchant_key, []):
            _assign(
                txn,
                category,
                CategorySource.LLM,
                result.confidence,
                needs_review=needs_review,
            )
            summary.by_classifier += 1

            if needs_review:
                summary.needs_review += 1

        # Only confident decisions become memos. Remembering a shaky guess
        # would quietly propagate it to every future transaction.
        if not needs_review:
            remember_merchant(result.merchant_key, category)

        classified.add(result.merchant_key)

    for merchant_key, transactions in awaiting.items():
        if merchant_key in classified:
            continue

        for txn in transactions:
            _assign_uncategorized(txn)
            summary.unmatched += 1
            summary.needs_review += 1

    return summary


def _assign(txn, category, source, confidence, needs_review=False):
    txn.category = category
    txn.category_source = source
    txn.category_confidence = confidence
    txn.needs_review = needs_review
    txn.merchant = txn.merchant or normalise_merchant(txn.description_raw)[:160]
    txn.save(
        update_fields=[
            "category", "category_source", "category_confidence",
            "needs_review", "merchant", "updated_at",
        ]
    )


def _assign_uncategorized(txn):
    """Park a transaction in the review queue rather than leaving it invisible."""
    category = Category.objects.filter(slug=UNCATEGORIZED_SLUG).first()

    txn.category = category
    txn.category_source = ""
    txn.category_confidence = 0.0
    txn.needs_review = True
    txn.save(
        update_fields=[
            "category", "category_source", "category_confidence",
            "needs_review", "updated_at",
        ]
    )


def confirm_category(transaction, category, user=None, *, remember=True):
    """Apply a human decision, and remember it for this merchant."""
    transaction.category = category
    transaction.category_source = CategorySource.MANUAL
    transaction.category_confidence = 1.0
    transaction.needs_review = False
    transaction.save(
        update_fields=[
            "category", "category_source", "category_confidence",
            "needs_review", "updated_at",
        ]
    )

    if remember:
        remember_merchant(normalise_merchant(transaction.description_raw), category, user)

    return transaction
