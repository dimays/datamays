from django.conf import settings
from django.db import models

from .base import TimestampedModel


class RecordType(models.TextChoices):
    TRANSACTIONS = "transactions", "Transactions"
    BALANCES = "balances", "Balances"
    PAYCHECK = "paycheck", "Paychecks"


class AmountConvention(models.TextChoices):
    """How a file expresses direction of money.

    Every institution does this differently, and getting it wrong silently
    inverts a whole statement — so it is an explicit, confirmed choice rather
    than something inferred and forgotten.
    """

    SIGNED = "signed", "One signed column (negative is money out)"
    SIGNED_INVERTED = "signed_inverted", "One signed column (positive is money out)"
    DEBIT_CREDIT = "debit_credit", "Separate debit and credit columns"


class ImportMapping(TimestampedModel):
    """A saved column mapping, reusable for the next file from the same source.

    Confirmed by a human once per institution and record type, then replayed.
    The point is that nobody has to re-derive which column was the date.
    """

    name = models.CharField(max_length=120)
    institution = models.ForeignKey(
        "finance.Institution",
        on_delete=models.CASCADE,
        related_name="import_mappings",
        null=True,
        blank=True,
    )
    record_type = models.CharField(
        max_length=20, choices=RecordType.choices, default=RecordType.TRANSACTIONS
    )

    column_map = models.JSONField(
        default=dict,
        help_text="Target field name → source column header.",
    )
    date_format = models.CharField(
        max_length=40,
        blank=True,
        help_text="strptime format. Empty means try the usual suspects.",
    )
    amount_convention = models.CharField(
        max_length=20, choices=AmountConvention.choices, default=AmountConvention.SIGNED
    )
    skip_rows = models.PositiveIntegerField(
        default=0, help_text="Preamble lines before the header row."
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="finance_import_mappings",
    )
    times_used = models.PositiveIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["institution__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["institution", "record_type", "name"],
                name="unique_mapping_name_per_institution_and_type",
            )
        ]

    def __str__(self):
        return f"{self.institution or 'Any'} — {self.name}"


class ImportStatus(models.TextChoices):
    UPLOADED = "uploaded", "Uploaded"
    NEEDS_MAPPING = "needs_mapping", "Awaiting column mapping"
    PREVIEW = "preview", "Ready to review"
    COMMITTED = "committed", "Committed"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class ImportBatch(TimestampedModel):
    """One uploaded file, from upload through to committed rows.

    Rows are staged and previewed before anything is written to the ledger, so
    a wrong mapping is caught on screen instead of in the dashboards.
    """

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="finance_imports",
    )
    institution = models.ForeignKey(
        "finance.Institution",
        on_delete=models.PROTECT,
        related_name="import_batches",
    )
    account = models.ForeignKey(
        "finance.Account",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="import_batches",
        help_text="Required for transaction and balance files.",
    )

    record_type = models.CharField(
        max_length=20, choices=RecordType.choices, default=RecordType.TRANSACTIONS
    )
    mapping = models.ForeignKey(
        ImportMapping,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="batches",
    )

    original_filename = models.CharField(max_length=255)
    raw_content = models.TextField(
        blank=True,
        help_text=(
            "The uploaded file's text. Kept in the database rather than on "
            "disk because Heroku's filesystem is ephemeral — a dyno restart "
            "between upload and mapping would otherwise lose the file "
            "mid-wizard. It also doubles as the audit trail."
        ),
    )

    status = models.CharField(
        max_length=20, choices=ImportStatus.choices, default=ImportStatus.UPLOADED
    )

    detected_headers = models.JSONField(default=list, blank=True)
    sample_rows = models.JSONField(
        default=list, blank=True, help_text="First few rows, for the mapping preview."
    )
    suggested_map = models.JSONField(
        default=dict, blank=True, help_text="What auto-detection proposed."
    )

    row_count = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    duplicate_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)

    committed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "import batches"

    def __str__(self):
        return f"{self.original_filename} ({self.status})"

    @property
    def is_committed(self):
        return self.status == ImportStatus.COMMITTED


class RowStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    OK = "ok", "Ready"
    DUPLICATE = "duplicate", "Already imported"
    ERROR = "error", "Could not parse"
    SKIPPED = "skipped", "Skipped"


class ImportRow(models.Model):
    """A single staged row, kept after commit as an audit trail."""

    batch = models.ForeignKey(
        ImportBatch, on_delete=models.CASCADE, related_name="rows"
    )
    row_number = models.PositiveIntegerField()

    raw = models.JSONField(default=dict, help_text="The source row, verbatim.")
    parsed = models.JSONField(
        default=dict, blank=True, help_text="After the mapping is applied."
    )

    status = models.CharField(
        max_length=20, choices=RowStatus.choices, default=RowStatus.PENDING
    )
    error_message = models.CharField(max_length=500, blank=True)

    transaction = models.ForeignKey(
        "finance.Transaction",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="import_rows",
    )

    class Meta:
        ordering = ["row_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "row_number"], name="unique_row_number_per_batch"
            )
        ]

    def __str__(self):
        return f"Row {self.row_number} ({self.status})"
