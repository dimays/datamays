"""Every view in the finance app, one module per screen area.

Re-exported here so `finance/urls.py` and the tests can import from
`finance.views` without caring which module a view lives in — the same
arrangement `finance.models` and `finance.forms` use.
"""

from .alerts import (
    AlertCreateView,
    AlertDeleteView,
    AlertListView,
    AlertUpdateView,
    ReportCreateView,
    ReportUpdateView,
)
from .auth import FinanceLoginView, FinanceLogoutView, OTPSetupView, OTPVerifyView
from .base import (
    FinancePageMixin,
    FinanceView,
    PageTitleMixin,
    PersonalObjectMixin,
)
from .budgets import (
    BudgetCreateView,
    BudgetDeleteView,
    BudgetListView,
    BudgetUpdateView,
)
from .dashboards import ChartsView
from .help import HelpView
from .home import HomeView
from .imports import (
    ImportListView,
    ImportMapView,
    ImportPreviewView,
    ImportSchemaView,
    ImportUploadView,
)
from .qfr import QFRDetailView, QFRListView
from .settings import (
    AccountCreateView,
    AccountUpdateView,
    CategoryCreateView,
    CategoryDeleteView,
    CategoryListView,
    CategoryUpdateView,
    ConnectionCreateView,
    ConnectionDetailView,
    InstitutionCreateView,
    InstitutionListView,
    InstitutionUpdateView,
    PreferencesView,
    RuleCreateView,
    RuleListView,
    SettingsHomeView,
)
from .transactions import TransactionListView

__all__ = [
    "AccountCreateView",
    "AccountUpdateView",
    "AlertCreateView",
    "AlertDeleteView",
    "AlertListView",
    "AlertUpdateView",
    "BudgetCreateView",
    "BudgetDeleteView",
    "BudgetListView",
    "BudgetUpdateView",
    "CategoryCreateView",
    "CategoryDeleteView",
    "CategoryListView",
    "CategoryUpdateView",
    "ChartsView",
    "ConnectionCreateView",
    "ConnectionDetailView",
    "FinanceLoginView",
    "FinanceLogoutView",
    "FinancePageMixin",
    "FinanceView",
    "HelpView",
    "HomeView",
    "ImportListView",
    "ImportMapView",
    "ImportPreviewView",
    "ImportSchemaView",
    "ImportUploadView",
    "InstitutionCreateView",
    "InstitutionListView",
    "InstitutionUpdateView",
    "OTPSetupView",
    "OTPVerifyView",
    "PageTitleMixin",
    "PersonalObjectMixin",
    "PreferencesView",
    "QFRDetailView",
    "QFRListView",
    "ReportCreateView",
    "ReportUpdateView",
    "RuleCreateView",
    "RuleListView",
    "SettingsHomeView",
    "TransactionListView",
]
