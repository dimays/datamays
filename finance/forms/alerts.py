"""Alerts and scheduled email reports — both personal, not household-wide."""

from django import forms

from ..models import Account, Alert, Budget, ScheduledReport
from ..services.reports import SECTION_CHOICES
from .base import StyledFormMixin


class AlertForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Alert
        fields = [
            "name", "kind", "account", "budget", "comparison", "threshold",
            "threshold_unit", "only_after_period_fraction", "cooldown_hours",
            "is_active",
        ]
        widgets = {
            "threshold": forms.NumberInput(attrs={"step": "0.01"}),
            "only_after_period_fraction": forms.NumberInput(
                attrs={"step": "0.05", "min": 0, "max": 1}
            ),
            "cooldown_hours": forms.NumberInput(attrs={"min": 1}),
        }
        help_texts = {
            "threshold": (
                "A dollar amount, a percentage for budget-percent alerts, or a "
                "count of the unit below for source-staleness alerts."
            ),
            "threshold_unit": "Only used by source-staleness alerts — hours, days, weeks, or months.",
            "only_after_period_fraction": (
                "Optional, 0–1. Only fire past this point in the budget period — "
                "0.5 means 'only in the second half of the month'."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = Account.objects.filter(is_active=True)
        self.fields["budget"].queryset = Budget.objects.filter(is_active=True)
        self.fields["account"].required = False
        self.fields["budget"].required = False
        self.fields["threshold_unit"].required = False


class ReportForm(StyledFormMixin, forms.ModelForm):
    sections_selected = forms.MultipleChoiceField(
        label="Include",
        choices=SECTION_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )

    class Meta:
        model = ScheduledReport
        fields = ["name", "cadence", "send_day", "is_active"]
        widgets = {
            "send_day": forms.NumberInput(attrs={"min": 1, "max": 28}),
        }
        help_texts = {"send_day": "Weekly: 1 is Monday. Monthly: day of the month, 1–28."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["sections_selected"].initial = self.instance.sections

    def save(self, commit=True):
        report = super().save(commit=False)

        chosen = set(self.cleaned_data["sections_selected"])
        # Canonical order, so the email always reads the same way.
        report.sections = [slug for slug, _ in SECTION_CHOICES if slug in chosen]

        if commit:
            report.save()

        return report
