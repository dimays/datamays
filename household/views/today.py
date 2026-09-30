"""Today: the landing page after sign-in, pulling every section together."""

from ..integrations import finance
from ..models import HouseholdPreference
from ..services import checklist
from .base import HouseholdView


class TodayView(HouseholdView):
    template_name = "household/today.html"
    page_title = "Today"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        preference = HouseholdPreference.for_user(self.request.user)
        context["preference"] = preference
        context.update(
            checklist.today_summary(self.request.user, include_partner=preference.show_partner_chores)
        )
        context["budgets"] = finance.budget_glance(self.request.user)
        return context
