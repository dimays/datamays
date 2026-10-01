"""Today: the landing page after sign-in, pulling every section together."""

from ..dates import household_today
from ..integrations import finance
from .base import HouseholdView


class TodayView(HouseholdView):
    template_name = "household/today.html"
    page_title = "Today"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["today"] = household_today()
        context["budgets"] = finance.budget_glance(self.request.user)
        return context
