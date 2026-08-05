"""Budget CRUD and the budget overview.

The overview leads with pace rather than raw attainment: being 80% through a
grocery budget is fine on the 25th and alarming on the 8th, and "can we afford
this?" is the question this screen exists to answer.
"""

from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .access import FinanceAccessMixin
from .dates import household_today
from .forms import BudgetForm
from .models import Budget
from .services.rollups import backfill_budget, roll_up_budget


class BudgetListView(FinanceAccessMixin, ListView):
    template_name = "finance/budgets/list.html"
    context_object_name = "budgets"

    def get_queryset(self):
        return Budget.objects.prefetch_related("categories", "accounts")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = household_today()

        rows = []

        for budget in context["budgets"]:
            period = budget.budget_periods.filter(
                period_start__lte=today, period_end__gte=today
            ).first()

            rows.append(
                {
                    "budget": budget,
                    "period": period,
                    "pace": period.pace_difference(today) if period else None,
                }
            )

        context["page_title"] = "Budgets"
        context["rows"] = rows
        return context


class BudgetCreateView(FinanceAccessMixin, CreateView):
    template_name = "finance/budgets/form.html"
    form_class = BudgetForm
    success_url = reverse_lazy("finance:budgets")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "New budget"
        return context

    def form_valid(self, form):
        response = super().form_valid(form)

        # Backfill so a new budget arrives with history rather than an empty
        # chart and a meaningless first period.
        backfill_budget(self.object)

        messages.success(self.request, f"Created “{self.object.name}”.")
        return response


class BudgetUpdateView(FinanceAccessMixin, UpdateView):
    template_name = "finance/budgets/form.html"
    form_class = BudgetForm
    model = Budget
    success_url = reverse_lazy("finance:budgets")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Edit budget"
        return context

    def form_valid(self, form):
        response = super().form_valid(form)

        # Categories or accounts may have changed, so the current period's
        # actual is stale until recomputed.
        roll_up_budget(self.object)

        messages.success(self.request, f"Updated “{self.object.name}”.")
        return response


class BudgetDeleteView(FinanceAccessMixin, DeleteView):
    template_name = "finance/budgets/confirm_delete.html"
    model = Budget
    success_url = reverse_lazy("finance:budgets")
    context_object_name = "budget"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Delete budget"
        return context

    def form_valid(self, form):
        messages.info(self.request, f"Deleted “{self.object.name}”.")
        return super().form_valid(form)
