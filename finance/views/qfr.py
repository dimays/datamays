"""Quarterly Finance Reports.

Generation makes a network call (an LLM narrative, optional) and only ever
covers a calendar quarter that's genuinely closed, so the list page offers it
as an explicit button rather than triggering it from a page load — a
deliberate, occasional action, just no longer CLI-only.
"""

from django.contrib import messages
from django.shortcuts import redirect
from django.views.generic import DetailView, ListView

from ..models import QuarterlyReport
from ..services.qfr import available_quarters_for_generation, generate_qfr
from .base import FinancePageMixin


class QFRListView(FinancePageMixin, ListView):
    template_name = "finance/qfr/list.html"
    context_object_name = "reports"
    model = QuarterlyReport
    page_title = "QFRs"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["available_quarters"] = available_quarters_for_generation()
        return context

    def post(self, request, *args, **kwargs):
        year, _, quarter = request.POST.get("quarter", "").partition("-")

        try:
            year, quarter = int(year), int(quarter)
        except ValueError:
            messages.error(request, "Pick a quarter to generate.")
            return redirect("finance:qfrs")

        available = {(y, q) for y, q, _ in available_quarters_for_generation()}

        if (year, quarter) not in available:
            messages.error(
                request,
                f"Q{quarter} {year} isn't available — it's either still open "
                "or not fully covered by transaction history yet.",
            )
            return redirect("finance:qfrs")

        report = generate_qfr(year, quarter)
        messages.success(request, f"Generated {report.label}.")
        return redirect("finance:qfr_detail", pk=report.pk)


class QFRDetailView(FinancePageMixin, DetailView):
    template_name = "finance/qfr/detail.html"
    context_object_name = "report"
    model = QuarterlyReport

    def get_page_title(self):
        return self.object.label

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        metrics = self.object.metrics or {}
        context["spend_by_category"] = sorted(
            (metrics.get("spend_by_category") or {}).items(),
            key=lambda item: item[1],
            reverse=True,
        )
        context["budgets"] = metrics.get("budgets") or []

        comparisons = self.object.comparisons or {}
        context["comparisons"] = comparisons
        context["comparison_list"] = [
            comparisons[key]
            for key in ("previous_quarter", "year_ago_quarter")
            if comparisons.get(key)
        ]

        return context
