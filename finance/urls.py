from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("transactions/", views.TransactionListView.as_view(), name="transactions"),
    path("charts/", views.ChartsView.as_view(), name="charts"),
    path("qfrs/", views.QFRListView.as_view(), name="qfrs"),
    path("qfrs/<int:pk>/", views.QFRDetailView.as_view(), name="qfr_detail"),
    path("settings/", views.SettingsHomeView.as_view(), name="settings"),
    path("settings/institutions/", views.InstitutionListView.as_view(), name="institutions"),
    path("settings/institutions/new/", views.InstitutionCreateView.as_view(), name="institution_create"),
    path("settings/institutions/<int:pk>/", views.InstitutionUpdateView.as_view(), name="institution_edit"),
    path("settings/connections/new/", views.ConnectionCreateView.as_view(), name="connection_create"),
    path("settings/connections/<int:pk>/", views.ConnectionDetailView.as_view(), name="connection_detail"),
    path("settings/accounts/new/", views.AccountCreateView.as_view(), name="account_create"),
    path("settings/accounts/<int:pk>/", views.AccountUpdateView.as_view(), name="account_edit"),
    path("settings/rules/", views.RuleListView.as_view(), name="rules"),
    path("settings/rules/new/", views.RuleCreateView.as_view(), name="rule_create"),
    path("settings/categories/", views.CategoryListView.as_view(), name="categories"),
    path("settings/categories/new/", views.CategoryCreateView.as_view(), name="category_create"),
    path("settings/categories/<int:pk>/", views.CategoryUpdateView.as_view(), name="category_edit"),
    path("settings/categories/<int:pk>/delete/", views.CategoryDeleteView.as_view(), name="category_delete"),
    path("preferences/", views.PreferencesView.as_view(), name="preferences"),
    path("help/", views.HelpView.as_view(), name="help"),
    # Alerts and reports
    path("alerts/", views.AlertListView.as_view(), name="alerts"),
    path("alerts/new/", views.AlertCreateView.as_view(), name="alert_create"),
    path("alerts/<int:pk>/", views.AlertUpdateView.as_view(), name="alert_edit"),
    path("alerts/<int:pk>/delete/", views.AlertDeleteView.as_view(), name="alert_delete"),
    path("reports/new/", views.ReportCreateView.as_view(), name="report_create"),
    path("reports/<int:pk>/", views.ReportUpdateView.as_view(), name="report_edit"),
    # Budgets
    path("budgets/", views.BudgetListView.as_view(), name="budgets"),
    path("budgets/new/", views.BudgetCreateView.as_view(), name="budget_create"),
    path("budgets/<int:pk>/", views.BudgetUpdateView.as_view(), name="budget_edit"),
    path("budgets/<int:pk>/delete/", views.BudgetDeleteView.as_view(), name="budget_delete"),
    # Imports
    path("imports/", views.ImportListView.as_view(), name="imports"),
    path("imports/schemas/", views.ImportSchemaView.as_view(), name="import_schemas"),
    path("imports/new/", views.ImportUploadView.as_view(), name="import_upload"),
    path("imports/<int:pk>/columns/", views.ImportMapView.as_view(), name="import_map"),
    path("imports/<int:pk>/review/", views.ImportPreviewView.as_view(), name="import_preview"),
    # Auth
    path("login/", views.FinanceLoginView.as_view(), name="login"),
    path("logout/", views.FinanceLogoutView.as_view(), name="logout"),
    path("two-factor/setup/", views.OTPSetupView.as_view(), name="otp_setup"),
    path("two-factor/", views.OTPVerifyView.as_view(), name="otp_verify"),
]
