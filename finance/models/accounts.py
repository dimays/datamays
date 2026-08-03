from django.db import models

from .base import TimestampedModel, money_field
from .institutions import AccountConnection, Institution


class AccountType(models.TextChoices):
    CHECKING = "checking", "Checking"
    SAVINGS = "savings", "Savings"
    MONEY_MARKET = "money_market", "Money market"
    CREDIT_CARD = "credit_card", "Credit card"
    STUDENT_LOAN = "student_loan", "Student loan"
    MORTGAGE = "mortgage", "Mortgage"
    AUTO_LOAN = "auto_loan", "Auto loan"
    INVESTMENT = "investment", "Investment"
    RETIREMENT = "retirement", "Retirement"
    INSURANCE = "insurance", "Insurance policy"
    OTHER = "other", "Other"


# Account types the household owes on. Balances for these are stored negative,
# so any set of balances sums straight to net worth.
LIABILITY_TYPES = frozenset(
    {
        AccountType.CREDIT_CARD,
        AccountType.STUDENT_LOAN,
        AccountType.MORTGAGE,
        AccountType.AUTO_LOAN,
    }
)

# Types that post day-to-day activity and so are worth syncing hourly. The rest
# move monthly at most and are picked up by the daily run.
HIGH_FREQUENCY_TYPES = frozenset(
    {
        AccountType.CHECKING,
        AccountType.SAVINGS,
        AccountType.MONEY_MARKET,
        AccountType.CREDIT_CARD,
    }
)


class Account(TimestampedModel):
    institution = models.ForeignKey(
        Institution, on_delete=models.PROTECT, related_name="accounts"
    )
    connection = models.ForeignKey(
        AccountConnection,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accounts",
        help_text="Empty for accounts maintained by CSV import or by hand.",
    )

    provider_account_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="The provider's stable identifier. Empty for manual accounts.",
    )

    name = models.CharField(max_length=160, help_text="What you call it.")
    official_name = models.CharField(
        max_length=255, blank=True, help_text="What the institution calls it."
    )
    mask = models.CharField(
        max_length=8, blank=True, help_text="Last few digits, for telling cards apart."
    )

    account_type = models.CharField(max_length=20, choices=AccountType.choices)
    currency = models.CharField(max_length=3, default="USD")

    # Denormalised from the newest snapshot so account lists and the homepage
    # do not need a subquery per account.
    current_balance = money_field(
        null=True,
        blank=True,
        help_text="Signed for net worth: assets positive, liabilities negative.",
    )
    available_balance = money_field(null=True, blank=True)
    credit_limit = money_field(null=True, blank=True)
    balance_as_of = models.DateTimeField(null=True, blank=True)

    debt_reported_positive = models.BooleanField(
        default=True,
        help_text=(
            "Most institutions report a debt as a positive 'amount owed'. "
            "Clear this if a liability's balance shows the wrong sign after a "
            "sync. Ignored for asset accounts."
        ),
    )

    is_active = models.BooleanField(default=True)
    include_in_net_worth = models.BooleanField(default=True)
    include_in_spending = models.BooleanField(
        default=True,
        help_text="Off for accounts whose activity would double-count spend.",
    )

    sort_order = models.PositiveIntegerField(default=100)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["sort_order", "institution__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "provider_account_id"],
                condition=~models.Q(provider_account_id=""),
                name="unique_provider_account_per_connection",
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.mask})" if self.mask else self.name

    @property
    def is_liability(self):
        return self.account_type in LIABILITY_TYPES

    @property
    def is_high_frequency(self):
        return self.account_type in HIGH_FREQUENCY_TYPES

    @property
    def is_manual(self):
        return self.connection_id is None

    @property
    def display_balance(self):
        """Balance as a person reads it: a debt of $1,200 shows as 1200.

        Storage stays signed for net worth; this is for presentation only.
        """
        if self.current_balance is None:
            return None
        return abs(self.current_balance) if self.is_liability else self.current_balance


class BalanceSource(models.TextChoices):
    PROVIDER = "provider", "Provider sync"
    CSV = "csv", "CSV import"
    MANUAL = "manual", "Manual entry"


class AccountBalanceSnapshot(models.Model):
    """A dated balance reading.

    Every time-series chart — net worth, debt paydown, savings growth — reads
    from here rather than reconstructing history from transactions, which is
    impossible for accounts that only ever report a balance (mortgage
    principal, a life policy's cash value, a 401k).
    """

    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="balance_snapshots"
    )
    as_of = models.DateField()

    current = money_field(help_text="Signed for net worth, as on Account.")
    available = money_field(null=True, blank=True)
    credit_limit = money_field(null=True, blank=True)

    source = models.CharField(
        max_length=20, choices=BalanceSource.choices, default=BalanceSource.PROVIDER
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-as_of"]
        constraints = [
            # One reading per account per day; a re-run overwrites rather than
            # stacking duplicate points onto the chart.
            models.UniqueConstraint(
                fields=["account", "as_of"], name="unique_balance_per_account_per_day"
            )
        ]
        indexes = [models.Index(fields=["account", "-as_of"])]

    def __str__(self):
        return f"{self.account} @ {self.as_of}: {self.current}"
