from decimal import Decimal

from django.conf import settings
from django.db import models

from .base import TimestampedModel, money_field


class DeductionKind(models.TextChoices):
    FEDERAL_TAX = "federal_tax", "Federal income tax"
    STATE_TAX = "state_tax", "State income tax"
    LOCAL_TAX = "local_tax", "Local tax"
    FICA = "fica", "Social Security & Medicare"
    RETIREMENT = "retirement", "Retirement contribution"
    HSA = "hsa", "HSA / FSA"
    INSURANCE = "insurance", "Insurance premium"
    OTHER = "other", "Other deduction"


# What "net of savings and retirement" means on the income dashboard: these
# reduce take-home pay but are still household money, so they are reported
# separately from money that genuinely leaves.
RETAINED_KINDS = frozenset({DeductionKind.RETIREMENT, DeductionKind.HSA})


class Paycheck(TimestampedModel):
    """A single pay event, gross through to net.

    Aggregators report the deposit, not the deductions behind it, so this is
    populated by CSV import or by hand from a payslip. Without it the income
    dashboard can only ever show take-home pay, which hides both the tax
    burden and the retirement contributions.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="paychecks"
    )
    employer = models.CharField(max_length=160)
    pay_date = models.DateField(db_index=True)

    gross = money_field()
    net = money_field()

    deposit_account = models.ForeignKey(
        "finance.Account",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="paychecks",
    )
    deposit_transaction = models.OneToOneField(
        "finance.Transaction",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="paycheck",
        help_text="The matching deposit, so income is not counted twice.",
    )

    import_batch = models.ForeignKey(
        "finance.ImportBatch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="paychecks",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-pay_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "employer", "pay_date"],
                name="unique_paycheck_per_employer_per_date",
            )
        ]

    def __str__(self):
        return f"{self.employer} {self.pay_date}: {self.net} net"

    @property
    def total_deductions(self):
        return sum((line.amount for line in self.deductions.all()), Decimal("0"))

    @property
    def retained_deductions(self):
        """Deductions that stay household money — retirement, HSA."""
        return sum(
            (
                line.amount
                for line in self.deductions.all()
                if line.kind in RETAINED_KINDS
            ),
            Decimal("0"),
        )

    @property
    def reconciles(self):
        """Whether gross minus deductions actually equals net.

        A mismatch means a payslip line was missed on import, which would
        silently understate the tax burden on the income dashboard.
        """
        return abs(self.gross - self.total_deductions - self.net) <= Decimal("0.02")


class PaycheckDeduction(models.Model):
    paycheck = models.ForeignKey(
        Paycheck, on_delete=models.CASCADE, related_name="deductions"
    )
    kind = models.CharField(max_length=20, choices=DeductionKind.choices)
    label = models.CharField(
        max_length=120, blank=True, help_text="The payslip's own wording."
    )
    amount = money_field(help_text="Positive: the amount withheld.")

    class Meta:
        ordering = ["kind"]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.amount}"
