from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .base import TimestampedModel, money_field

# Homepage widgets, in the order they render by default. Stored as slugs in
# UserPreference so each person arranges their own homepage.
DEFAULT_HOMEPAGE_WIDGETS = ["balances", "budgets", "recent_transactions"]


class UserPreference(TimestampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="finance_preferences",
    )

    homepage_widgets = models.JSONField(
        default=list, blank=True, help_text="Widget slugs, in display order."
    )
    homepage_account_ids = models.JSONField(
        default=list, blank=True, help_text="Empty means every account."
    )
    homepage_budget_ids = models.JSONField(default=list, blank=True)

    dashboard_filters = models.JSONField(
        default=dict,
        blank=True,
        help_text="Per-dashboard filter state, keyed by dashboard slug.",
    )

    recent_transaction_count = models.PositiveIntegerField(default=8)

    class Meta:
        ordering = ["user__username"]

    def __str__(self):
        return f"Preferences for {self.user}"

    @property
    def widgets(self):
        return self.homepage_widgets or list(DEFAULT_HOMEPAGE_WIDGETS)

    @classmethod
    def for_user(cls, user):
        preference, _ = cls.objects.get_or_create(
            user=user, defaults={"homepage_widgets": list(DEFAULT_HOMEPAGE_WIDGETS)}
        )
        return preference


class AlertKind(models.TextChoices):
    ACCOUNT_BALANCE = "account_balance", "Account balance crosses a threshold"
    BUDGET_PERCENT = "budget_percent", "Budget reaches a percentage"
    BUDGET_AMOUNT = "budget_amount", "Budget spend reaches an amount"


class Comparison(models.TextChoices):
    ABOVE = "above", "Rises above"
    BELOW = "below", "Falls below"


class Alert(TimestampedModel):
    """A threshold worth being told about by email."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="finance_alerts"
    )
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=30, choices=AlertKind.choices)

    account = models.ForeignKey(
        "finance.Account",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="alerts",
    )
    budget = models.ForeignKey(
        "finance.Budget",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="alerts",
    )

    comparison = models.CharField(
        max_length=10, choices=Comparison.choices, default=Comparison.ABOVE
    )
    threshold = money_field(
        help_text="A currency amount, or a percentage for budget-percent alerts."
    )

    only_after_period_fraction = models.FloatField(
        null=True,
        blank=True,
        help_text=(
            "0–1. Only fire past this point in the budget period, so "
            "'80% of the grocery budget before the 15th' is expressible."
        ),
    )

    is_active = models.BooleanField(default=True)
    cooldown_hours = models.PositiveIntegerField(
        default=24, help_text="Minimum gap between repeats of the same alert."
    )
    last_triggered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        if self.kind == AlertKind.ACCOUNT_BALANCE and self.account_id is None:
            raise ValidationError({"account": "Pick the account to watch."})

        if self.kind in {AlertKind.BUDGET_PERCENT, AlertKind.BUDGET_AMOUNT} and self.budget_id is None:
            raise ValidationError({"budget": "Pick the budget to watch."})

        if self.only_after_period_fraction is not None and not (
            0 <= self.only_after_period_fraction <= 1
        ):
            raise ValidationError(
                {"only_after_period_fraction": "Use a value between 0 and 1."}
            )


class AlertEvent(models.Model):
    """One firing, recorded so alerts can be deduplicated and audited."""

    alert = models.ForeignKey(Alert, on_delete=models.CASCADE, related_name="events")
    triggered_at = models.DateTimeField(auto_now_add=True)

    observed_value = money_field()
    message = models.TextField()
    was_delivered = models.BooleanField(default=False)
    delivery_error = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-triggered_at"]
        indexes = [models.Index(fields=["alert", "-triggered_at"])]

    def __str__(self):
        return f"{self.alert.name} @ {self.triggered_at:%Y-%m-%d %H:%M}"


class ReportCadence(models.TextChoices):
    WEEKLY = "weekly", "Weekly"
    MONTHLY = "monthly", "Monthly"


class ScheduledReport(TimestampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="finance_reports",
    )
    name = models.CharField(max_length=120, default="Household summary")
    cadence = models.CharField(
        max_length=20, choices=ReportCadence.choices, default=ReportCadence.WEEKLY
    )

    sections = models.JSONField(
        default=list,
        blank=True,
        help_text="Section slugs to include, e.g. balances, budgets, spend.",
    )
    account_ids = models.JSONField(default=list, blank=True)
    budget_ids = models.JSONField(default=list, blank=True)

    send_day = models.PositiveSmallIntegerField(
        default=1,
        help_text="Weekly: 1 is Monday. Monthly: day of the month.",
    )
    is_active = models.BooleanField(default=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["user__username", "name"]

    def __str__(self):
        return f"{self.name} ({self.get_cadence_display().lower()}) for {self.user}"

    def clean(self):
        if self.cadence == ReportCadence.WEEKLY and not (1 <= self.send_day <= 7):
            raise ValidationError({"send_day": "Use 1 (Monday) through 7 (Sunday)."})

        if self.cadence == ReportCadence.MONTHLY and not (1 <= self.send_day <= 28):
            raise ValidationError(
                {"send_day": "Use 1–28 so the report exists in every month."}
            )
