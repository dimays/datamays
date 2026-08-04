from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .base import TimestampedModel, money_field

# Homepage widgets, in the order they render by default. Stored as slugs in
# UserPreference so each person arranges their own homepage.
DEFAULT_HOMEPAGE_WIDGETS = ["balances", "budgets", "recent_transactions"]

# Charts tab sections, in the order they render by default — the same
# arrange-your-own pattern as the homepage widgets above, one level down.
DEFAULT_CHART_SECTIONS = [
    "spend_over_time",
    "spend_by_category_trend",
    "spend_by_category",
    "budget_attainment",
    "net_income",
    "net_cash_flow",
    "savings_debt",
]


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
    chart_sections = models.JSONField(
        default=list, blank=True, help_text="Charts tab section slugs, in display order."
    )

    recent_transaction_count = models.PositiveIntegerField(default=8)

    class Meta:
        ordering = ["user__username"]

    def __str__(self):
        return f"Preferences for {self.user}"

    @property
    def widgets(self):
        return self.homepage_widgets or list(DEFAULT_HOMEPAGE_WIDGETS)

    @property
    def chart_section_order(self):
        return self.chart_sections or list(DEFAULT_CHART_SECTIONS)

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
    SOURCE_STALE = "source_stale", "Account hasn't synced or been updated"


class ThresholdUnit(models.TextChoices):
    HOURS = "hours", "Hours"
    DAYS = "days", "Days"
    WEEKS = "weeks", "Weeks"
    MONTHS = "months", "Months"


# Used only to compare a SOURCE_STALE alert's threshold_unit against its
# threshold on a common footing. Months are a 30-day approximation — fine for
# "when do I need to look at this again", not meant for exact bookkeeping.
UNIT_HOURS = {
    ThresholdUnit.HOURS: 1,
    ThresholdUnit.DAYS: 24,
    ThresholdUnit.WEEKS: 24 * 7,
    ThresholdUnit.MONTHS: 24 * 30,
}


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
        help_text=(
            "A currency amount, a percentage for budget-percent alerts, or a "
            "count of threshold_unit for source-staleness alerts."
        ),
    )
    threshold_unit = models.CharField(
        max_length=10,
        choices=ThresholdUnit.choices,
        blank=True,
        help_text=(
            "Only meaningful for source-staleness alerts: the unit threshold "
            "is counted in — 'hasn't synced in more than 3 days' stores "
            "threshold=3, threshold_unit=days."
        ),
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
        if self.kind in {AlertKind.ACCOUNT_BALANCE, AlertKind.SOURCE_STALE} and self.account_id is None:
            raise ValidationError({"account": "Pick the account to watch."})

        if self.kind in {AlertKind.BUDGET_PERCENT, AlertKind.BUDGET_AMOUNT} and self.budget_id is None:
            raise ValidationError({"budget": "Pick the budget to watch."})

        if self.kind == AlertKind.SOURCE_STALE:
            if not self.threshold_unit:
                raise ValidationError(
                    {"threshold_unit": "Pick a unit — hours, days, weeks, or months."}
                )
            # Staleness is inherently "more time has passed than this" — a
            # BELOW comparison has no sensible reading, so it is not offered
            # as a choice here; this just guards a value set outside the form.
            self.comparison = Comparison.ABOVE

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
