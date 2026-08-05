"""Alert and report configuration.

Both are personal — each person gets their own alerts at their own thresholds,
delivered to their own address — so every queryset is scoped to the signed-in
user rather than to the household. `PersonalObjectMixin` is what enforces
that; see its docstring in base.py.
"""

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from ..forms import AlertForm, ReportForm
from ..models import Alert, ScheduledReport
from ..services.reports import send_report
from .base import FinancePageMixin, PersonalObjectMixin


class AlertListView(PersonalObjectMixin, FinancePageMixin, ListView):
    template_name = "finance/alerts/list.html"
    context_object_name = "alerts"
    model = Alert
    page_title = "Alerts & reports"

    def get_queryset(self):
        return super().get_queryset().select_related("account", "budget")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Personal, same as the alerts above — the page shows both.
        context["reports"] = ScheduledReport.objects.filter(user=self.request.user)
        return context


class AlertCreateView(PersonalObjectMixin, FinancePageMixin, CreateView):
    template_name = "finance/alerts/form.html"
    form_class = AlertForm
    model = Alert
    success_url = reverse_lazy("finance:alerts")
    page_title = "New alert"

    def form_valid(self, form):
        messages.success(self.request, f"Created “{form.instance.name}”.")
        return super().form_valid(form)


class AlertUpdateView(PersonalObjectMixin, FinancePageMixin, UpdateView):
    template_name = "finance/alerts/form.html"
    form_class = AlertForm
    model = Alert
    success_url = reverse_lazy("finance:alerts")
    page_title = "Edit alert"


class AlertDeleteView(PersonalObjectMixin, FinancePageMixin, DeleteView):
    template_name = "finance/alerts/confirm_delete.html"
    model = Alert
    success_url = reverse_lazy("finance:alerts")
    context_object_name = "alert"
    page_title = "Delete alert"


class ReportCreateView(PersonalObjectMixin, FinancePageMixin, CreateView):
    template_name = "finance/alerts/report_form.html"
    form_class = ReportForm
    model = ScheduledReport
    success_url = reverse_lazy("finance:alerts")
    page_title = "New report"

    def form_valid(self, form):
        messages.success(self.request, f"Created “{form.instance.name}”.")
        return super().form_valid(form)


class ReportUpdateView(PersonalObjectMixin, FinancePageMixin, UpdateView):
    template_name = "finance/alerts/report_form.html"
    form_class = ReportForm
    model = ScheduledReport
    success_url = reverse_lazy("finance:alerts")
    page_title = "Edit report"

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
