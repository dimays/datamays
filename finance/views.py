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


class PlaceholderView(FinanceView):
    """Stands in for a screen that a later branch in this stack delivers."""

    template_name = "finance/placeholder.html"
    delivered_by = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["delivered_by"] = self.delivered_by
        return context


class SpendView(PlaceholderView):
    page_title = "Spend"
    delivered_by = "finance/dashboards"


class IncomeView(PlaceholderView):
    page_title = "Income"
    delivered_by = "finance/dashboards"


class SavingsView(PlaceholderView):
    page_title = "Savings & Debt"
    delivered_by = "finance/dashboards"


class SettingsView(PlaceholderView):
    page_title = "Settings"
    delivered_by = "finance/settings-preferences"


class PreferencesView(PlaceholderView):
    page_title = "Preferences"
    delivered_by = "finance/settings-preferences"
