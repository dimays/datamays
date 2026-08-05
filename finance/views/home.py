"""The homepage: whichever widgets this person chose, in their order."""

from ..services.widgets import build_homepage
from .base import FinanceView


class HomeView(FinanceView):
    template_name = "finance/home.html"
    page_title = "Home"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(build_homepage(self.request.user))
        return context
