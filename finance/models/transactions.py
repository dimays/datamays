import hashlib

from django.db import models

from .base import TimestampedModel, money_field


class CategorySource(models.TextChoices):
    RULE = "rule", "Rule"
    MEMO = "memo", "Remembered merchant"
    LLM = "llm", "Classifier"
    MANUAL = "manual", "Set by hand"
    TRANSFER = "transfer", "Transfer detection"


class TransactionSource(models.TextChoices):
    PROVIDER = "provider", "Provider sync"
    CSV = "csv", "CSV import"
    MANUAL = "manual", "Manual entry"


def build_fingerprint(*, account_id, posted_on, amount, description, sequence=0):
    """A stable identity for a transaction with no provider ID.

    CSV exports rarely carry stable identifiers, so re-importing an overlapping
    date range would otherwise duplicate everything. `sequence` distinguishes
    genuinely repeated transactions — two identical coffees on the same day are
    two rows, not one — and the importer assigns it by counting existing
    matches.
    """
    raw = "|".join(
        [
            str(account_id),
            posted_on.isoformat(),
            f"{amount:.2f}",
            (description or "").strip().casefold(),
            str(sequence),
        ]
    )

    return hashlib.sha256(raw.encode()).hexdigest()


class Transaction(TimestampedModel):
    """One posted movement of money.

    Sign convention (see models.base): negative leaves the household, positive
    arrives — on every account type, credit cards included.
    """

    account = models.ForeignKey(
        "finance.Account", on_delete=models.CASCADE, related_name="transactions"
    )

    provider_txn_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="The provider's stable ID. Empty for CSV and manual rows.",
    )
    fingerprint = models.CharField(
        max_length=64,
        help_text="Deterministic identity used to deduplicate imports.",
    )

    posted_on = models.DateField(db_index=True)
    amount = money_field()

    description_raw = models.CharField(
        max_length=500, help_text="Exactly as the institution supplied it."
    )
    merchant = models.CharField(
        max_length=160,
        blank=True,
        help_text="Cleaned-up merchant name, when one can be worked out.",
    )

    category = models.ForeignKey(
        "finance.Category",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
    )
    category_source = models.CharField(
        max_length=20, choices=CategorySource.choices, blank=True
    )
    category_confidence = models.FloatField(
        null=True,
        blank=True,
        help_text="0–1. Rules and manual edits are 1.0; low values queue for review.",
    )
    needs_review = models.BooleanField(default=False, db_index=True)

    is_pending = models.BooleanField(default=False)
    is_transfer = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Excluded from spend and income totals.",
    )
    transfer_pair = models.OneToOneField(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="paired_with",
        help_text="The matching leg on the other account.",
    )

    source = models.CharField(
        max_length=20, choices=TransactionSource.choices, default=TransactionSource.PROVIDER
    )
    import_batch = models.ForeignKey(
        "finance.ImportBatch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
    )

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-posted_on", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["account", "provider_txn_id"],
                condition=~models.Q(provider_txn_id=""),
                name="unique_provider_txn_per_account",
            ),
            models.UniqueConstraint(
                fields=["account", "fingerprint"],
                name="unique_fingerprint_per_account",
            ),
        ]
        indexes = [
            models.Index(fields=["-posted_on", "account"]),
            models.Index(fields=["category", "-posted_on"]),
            # Spend and budget rollups always filter out transfers first.
            models.Index(fields=["is_transfer", "-posted_on"]),
        ]

    def __str__(self):
        return f"{self.posted_on} {self.description_raw[:40]} {self.amount}"

    @property
    def is_outflow(self):
        return self.amount < 0

    @property
    def display_amount(self):
        return abs(self.amount)

    def ensure_fingerprint(self, sequence=0):
        if not self.fingerprint:
            self.fingerprint = build_fingerprint(
                account_id=self.account_id,
                posted_on=self.posted_on,
                amount=self.amount,
                description=self.description_raw,
                sequence=sequence,
            )
        return self.fingerprint

    def save(self, *args, **kwargs):
        self.ensure_fingerprint()
        super().save(*args, **kwargs)
