from .base import FinanceView


class HelpView(FinanceView):
    template_name = "finance/help.html"
    page_title = "Help"
