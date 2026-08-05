"""Alert and report configuration.

Both are personal — each person gets their own alerts at their own thresholds,
delivered to their own address — so every queryset is scoped to the signed-in
user rather than to the household.
"""

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .access import FinanceAccessMixin
from .forms import AlertForm, ReportForm
from .models import Alert, ScheduledReport
from .services.reports import send_report


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
