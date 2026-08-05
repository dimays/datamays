from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from .. import periods
from ..dates import household_today
from .base import TimestampedModel, money_field


class BudgetPeriodType(models.TextChoices):
    WEEKLY = "weekly", "Weekly"
    MONTHLY = "monthly", "Monthly"
    ANNUAL = "annual", "Annual"


class Budget(TimestampedModel):
    """A spending target over a repeating window.

    A budget can span several categories and be limited to particular
    accounts, so "eating out, but only on the credit cards" is expressible
    without inventing a category for it.
    """

    name = models.CharField(max_length=120)
    amount = money_field(
        validators=[MinValueValidator(0)],
        help_text="The target, as a positive number.",
    )

    period_type = models.CharField(
        max_length=20,
        choices=BudgetPeriodType.choices,
        default=BudgetPeriodType.MONTHLY,
    )
    anchor_date = models.DateField(
        default=date(2026, 1, 1),
        help_text=(
            "Sets the phase of the cycle: which weekday a weekly budget resets "
            "on, or which day of the month a monthly one does."
        ),
    )

    categories = models.ManyToManyField(
        "finance.Category", related_name="budgets", blank=True
    )
    accounts = models.ManyToManyField(
        "finance.Account",
        related_name="budgets",
        blank=True,
        help_text="Leave empty to count spending on every account.",
    )

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="finance_budgets",
        help_text="Empty means the budget belongs to the household.",
    )

    is_active = models.BooleanField(default=True)
    rollover = models.BooleanField(
        default=False,
        help_text="Carry an underspend or overspend into the next period.",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_period_type_display().lower()})"

    def clean(self):
        if self.amount is not None and self.amount < 0:
            raise ValidationError({"amount": "Enter the target as a positive number."})

    def period_for(self, on_date=None):
        on_date = on_date or household_today()
        return periods.period_containing(self.period_type, self.anchor_date, on_date)

    def current_period(self):
        return self.period_for()


class BudgetPeriod(models.Model):
    """Materialized target-versus-actual for one budget in one window.

    Recomputed by the rollup job rather than derived on page load: the
    homepage shows every active budget at once, and doing that live would mean
    an aggregate query per budget on every request from a phone.
    """

    budget = models.ForeignKey(
        Budget, on_delete=models.CASCADE, related_name="budget_periods"
    )

    period_start = models.DateField()
    period_end = models.DateField()

    target_amount = money_field(help_text="Includes any rollover from last period.")
    actual_amount = money_field(
        default=0, help_text="Spend so far, as a positive number."
    )
    rollover_amount = money_field(
        default=0, help_text="Carried in from the previous period."
    )

    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period_start"]
        constraints = [
            models.UniqueConstraint(
                fields=["budget", "period_start"], name="unique_period_per_budget"
            )
        ]
        indexes = [models.Index(fields=["budget", "-period_start"])]

    def __str__(self):
        return f"{self.budget.name} {self.period_start} — {self.actual_amount}/{self.target_amount}"

    @property
    def remaining(self):
        return self.target_amount - self.actual_amount

    @property
    def attainment(self):
        """Fraction of the target spent. None when the target is zero."""
        if not self.target_amount:
            return None
        return float(self.actual_amount / self.target_amount)

    @property
    def is_over(self):
        return self.actual_amount > self.target_amount

    @property
    def overspend(self):
        return max(Decimal("0"), self.actual_amount - self.target_amount)

    @property
    def bar_width(self):
        """Progress bar width, capped at 100 so an overspend cannot overflow."""
        if not self.target_amount:
            return 0

        return min(100, int(self.actual_amount / self.target_amount * 100))

    @property
    def elapsed_percent(self):
        """Where an even spend rate would put you today, as a percentage."""
        return round(
            periods.elapsed_fraction(
                self.period_start, self.period_end, household_today()
            )
            * 100
        )

    def pace_difference(self, on_date=None):
        """Actual spend minus what an even pace would predict by now.

        Positive means running hot. This is the number that answers "can we
        afford this?" — being 80% through a budget is fine on the 25th and
        alarming on the 8th.
        """
        on_date = on_date or household_today()
        elapsed = periods.elapsed_fraction(self.period_start, self.period_end, on_date)

        expected = self.target_amount * Decimal(str(round(elapsed, 6)))

        return self.actual_amount - expected
