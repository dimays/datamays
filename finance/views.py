from django.views.generic import TemplateView

from .access import FinanceAccessMixin


class FinanceView(FinanceAccessMixin, TemplateView):
    """Base for every finance page: gated, with a title for the header."""

    page_title = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.page_title
        return context


class HomeView(FinanceView):
    template_name = "finance/home.html"
    page_title = "Home"

    def get_context_data(self, **kwargs):
        from .services.widgets import build_homepage

        context = super().get_context_data(**kwargs)
        context.update(build_homepage(self.request.user))
        return context
