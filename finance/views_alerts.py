"""Alert and report configuration.

Both are personal — each person gets their own alerts at their own thresholds,
delivered to their own address — so every queryset is scoped to the signed-in
user rather than to the household.
"""

from django import forms
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .access import FinanceAccessMixin
from .models import Account, Alert, Budget, ScheduledReport
from .services.reports import SECTION_CHOICES, send_report

FIELD_CLASSES = (
    "w-full rounded-button border border-border bg-background px-3 py-2 text-sm "
    "text-text-primary focus:outline-none focus:ring-2 focus:ring-primary"
)

CHECKBOX_CLASSES = (
    "h-4 w-4 rounded border-border bg-background text-primary focus:ring-primary"
)


class AlertForm(forms.ModelForm):
    class Meta:
        model = Alert
        fields = [
            "name", "kind", "account", "budget", "comparison", "threshold",
            "threshold_unit", "only_after_period_fraction", "cooldown_hours",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": FIELD_CLASSES}),
            "kind": forms.Select(attrs={"class": FIELD_CLASSES}),
            "account": forms.Select(attrs={"class": FIELD_CLASSES}),
            "budget": forms.Select(attrs={"class": FIELD_CLASSES}),
            "comparison": forms.Select(attrs={"class": FIELD_CLASSES}),
            "threshold": forms.NumberInput(attrs={"class": FIELD_CLASSES, "step": "0.01"}),
            "threshold_unit": forms.Select(attrs={"class": FIELD_CLASSES}),
            "only_after_period_fraction": forms.NumberInput(
                attrs={"class": FIELD_CLASSES, "step": "0.05", "min": 0, "max": 1}
            ),
            "cooldown_hours": forms.NumberInput(attrs={"class": FIELD_CLASSES, "min": 1}),
            "is_active": forms.CheckboxInput(attrs={"class": CHECKBOX_CLASSES}),
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


class AlertListView(FinanceAccessMixin, ListView):
    template_name = "finance/alerts/list.html"
    context_object_name = "alerts"

    def get_queryset(self):
        # Personal: never surface the other person's thresholds.
        return Alert.objects.filter(user=self.request.user).select_related(
            "account", "budget"
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Alerts & reports"
        context["reports"] = ScheduledReport.objects.filter(user=self.request.user)
        return context


class AlertCreateView(FinanceAccessMixin, CreateView):
    template_name = "finance/alerts/form.html"
    form_class = AlertForm
    success_url = reverse_lazy("finance:alerts")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "New alert"
        return context

    def form_valid(self, form):
        form.instance.user = self.request.user
        messages.success(self.request, f"Created “{form.instance.name}”.")
        return super().form_valid(form)


class AlertUpdateView(FinanceAccessMixin, UpdateView):
    template_name = "finance/alerts/form.html"
    form_class = AlertForm
    success_url = reverse_lazy("finance:alerts")

    def get_queryset(self):
        return Alert.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Edit alert"
        return context


class AlertDeleteView(FinanceAccessMixin, DeleteView):
    template_name = "finance/alerts/confirm_delete.html"
    success_url = reverse_lazy("finance:alerts")
    context_object_name = "alert"

    def get_queryset(self):
        return Alert.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Delete alert"
        return context


class ReportForm(forms.ModelForm):
    sections_selected = forms.MultipleChoiceField(
        label="Include",
        choices=SECTION_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": CHECKBOX_CLASSES}),
    )

    class Meta:
        model = ScheduledReport
        fields = ["name", "cadence", "send_day", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": FIELD_CLASSES}),
            "cadence": forms.Select(attrs={"class": FIELD_CLASSES}),
            "send_day": forms.NumberInput(attrs={"class": FIELD_CLASSES, "min": 1, "max": 28}),
            "is_active": forms.CheckboxInput(attrs={"class": CHECKBOX_CLASSES}),
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


class ReportCreateView(FinanceAccessMixin, CreateView):
    template_name = "finance/alerts/report_form.html"
    form_class = ReportForm
    success_url = reverse_lazy("finance:alerts")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "New report"
        return context

    def form_valid(self, form):
        form.instance.user = self.request.user
        messages.success(self.request, f"Created “{form.instance.name}”.")
        return super().form_valid(form)


class ReportUpdateView(FinanceAccessMixin, UpdateView):
    template_name = "finance/alerts/report_form.html"
    form_class = ReportForm
    success_url = reverse_lazy("finance:alerts")

    def get_queryset(self):
        return ScheduledReport.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Edit report"
        return context

    def post(self, request, *args, **kwargs):
        if request.POST.get("action") == "send_test":
            report = self.get_object()

            if send_report(report):
                messages.success(request, f"Sent a copy to {request.user.email}.")
            else:
                messages.error(
                    request,
                    "Could not send — check the address on your account and the mail settings.",
                )

            return redirect("finance:report_edit", pk=report.pk)

        return super().post(request, *args, **kwargs)
