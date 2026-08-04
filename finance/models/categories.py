import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .base import TimestampedModel, money_field

MAX_CATEGORY_DEPTH = 3


class CategoryKind(models.TextChoices):
    EXPENSE = "expense", "Expense"
    INCOME = "income", "Income"
    TRANSFER = "transfer", "Transfer"


class Category(TimestampedModel):
    """A node in the household's category tree.

    Nesting is capped at three levels. Deeper trees are harder to hold in your
    head than the reporting benefit justifies, and the LLM classifies more
    consistently against a shallow list.
    """

    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=100, unique=True)
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
    )
    kind = models.CharField(
        max_length=20, choices=CategoryKind.choices, default=CategoryKind.EXPENSE
    )

    is_system = models.BooleanField(
        default=False,
        help_text="Seeded categories the app depends on by slug. Not deletable.",
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=100)
    description = models.CharField(
        max_length=255,
        blank=True,
        help_text="Steers the classifier — say what belongs here and what doesn't.",
    )

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "categories"
        constraints = [
            models.UniqueConstraint(
                fields=["parent", "name"], name="unique_category_name_per_parent"
            )
        ]

    def __str__(self):
        return self.full_path

    @property
    def depth(self):
        depth, node = 1, self
        while node.parent_id is not None:
            depth += 1
            node = node.parent
        return depth

    @property
    def full_path(self):
        parts, node = [], self
        while node is not None:
            parts.append(node.name)
            node = node.parent
        return " › ".join(reversed(parts))

    def clean(self):
        if self.parent_id == self.pk and self.pk is not None:
            raise ValidationError({"parent": "A category cannot be its own parent."})

        if self.parent and self.parent.depth >= MAX_CATEGORY_DEPTH:
            raise ValidationError(
                {"parent": f"Categories nest at most {MAX_CATEGORY_DEPTH} levels deep."}
            )

        if self.parent and self.parent.kind != self.kind:
            raise ValidationError(
                {"kind": "A subcategory must share its parent's kind."}
            )


class MatchType(models.TextChoices):
    CONTAINS = "contains", "Contains"
    STARTS_WITH = "starts_with", "Starts with"
    EXACT = "exact", "Exactly matches"
    REGEX = "regex", "Regular expression"


class CategoryRule(TimestampedModel):
    """A deterministic description-to-category mapping.

    Rules run before the classifier and always win. They exist so the
    categories you care about most are never at the mercy of a model's
    judgement — and so a mistake can be corrected permanently in one place.
    """

    pattern = models.CharField(max_length=255)
    match_type = models.CharField(
        max_length=20, choices=MatchType.choices, default=MatchType.CONTAINS
    )
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, related_name="rules"
    )

    account = models.ForeignKey(
        "finance.Account",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="category_rules",
        help_text="Limit the rule to one account. Empty applies it everywhere.",
    )
    min_amount = money_field(
        null=True, blank=True, help_text="Signed, inclusive lower bound."
    )
    max_amount = money_field(
        null=True, blank=True, help_text="Signed, inclusive upper bound."
    )

    priority = models.IntegerField(
        default=100, help_text="Lower runs first. The first match wins."
    )
    is_active = models.BooleanField(default=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["priority", "pattern"]

    def __str__(self):
        return f"{self.get_match_type_display()} '{self.pattern}' → {self.category}"

    def clean(self):
        if self.match_type == MatchType.REGEX:
            try:
                re.compile(self.pattern)
            except re.error as exc:
                raise ValidationError({"pattern": f"Invalid regular expression: {exc}"})

        if (
            self.min_amount is not None
            and self.max_amount is not None
            and self.min_amount > self.max_amount
        ):
            raise ValidationError(
                {"max_amount": "The upper bound must not be below the lower bound."}
            )

    def matches(self, *, description, amount, account_id=None):
        if not self.is_active:
            return False

        if self.account_id is not None and self.account_id != account_id:
            return False

        if self.min_amount is not None and amount < self.min_amount:
            return False

        if self.max_amount is not None and amount > self.max_amount:
            return False

        haystack = (description or "").casefold()
        needle = self.pattern.casefold()

        if self.match_type == MatchType.CONTAINS:
            return needle in haystack
        if self.match_type == MatchType.STARTS_WITH:
            return haystack.startswith(needle)
        if self.match_type == MatchType.EXACT:
            return haystack == needle
        if self.match_type == MatchType.REGEX:
            return re.search(self.pattern, description or "", re.IGNORECASE) is not None

        return False


class MerchantCategoryMemo(TimestampedModel):
    """A remembered merchant-to-category decision.

    This is what keeps the classifier cheap. Recurring merchants are most of a
    household's activity, so once a merchant is confirmed it never needs to be
    sent to the model again.
    """

    merchant_key = models.CharField(
        max_length=160,
        unique=True,
        help_text="Normalised merchant string (see services.categorize).",
    )
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, related_name="merchant_memos"
    )

    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="finance_memos",
        help_text="Empty when the memo came from an accepted classification.",
    )
    hit_count = models.PositiveIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["merchant_key"]

    def __str__(self):
        return f"{self.merchant_key} → {self.category}"
