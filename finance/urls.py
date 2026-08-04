from django.urls import path

from . import (
    views,
    views_alerts,
    views_auth,
    views_budgets,
    views_dashboards,
    views_help,
    views_imports,
    views_qfr,
    views_settings,
    views_transactions,
)

app_name = "finance"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("transactions/", views_transactions.TransactionListView.as_view(), name="transactions"),
    path("spend/", views_dashboards.SpendView.as_view(), name="spend"),
    path("income/", views_dashboards.IncomeView.as_view(), name="income"),
    path("savings/", views_dashboards.SavingsView.as_view(), name="savings"),
    path("qfrs/", views_qfr.QFRListView.as_view(), name="qfrs"),
    path("qfrs/<int:pk>/", views_qfr.QFRDetailView.as_view(), name="qfr_detail"),
    path("settings/", views_settings.SettingsHomeView.as_view(), name="settings"),
    path("settings/institutions/", views_settings.InstitutionListView.as_view(), name="institutions"),
    path("settings/institutions/new/", views_settings.InstitutionCreateView.as_view(), name="institution_create"),
    path("settings/institutions/<int:pk>/", views_settings.InstitutionUpdateView.as_view(), name="institution_edit"),
    path("settings/connections/new/", views_settings.ConnectionCreateView.as_view(), name="connection_create"),
    path("settings/connections/<int:pk>/", views_settings.ConnectionDetailView.as_view(), name="connection_detail"),
    path("settings/accounts/new/", views_settings.AccountCreateView.as_view(), name="account_create"),
    path("settings/accounts/<int:pk>/", views_settings.AccountUpdateView.as_view(), name="account_edit"),
    path("settings/rules/", views_settings.RuleListView.as_view(), name="rules"),
    path("preferences/", views_settings.PreferencesView.as_view(), name="preferences"),
    path("help/", views_help.HelpView.as_view(), name="help"),
    # Alerts and reports
    path("alerts/", views_alerts.AlertListView.as_view(), name="alerts"),
    path("alerts/new/", views_alerts.AlertCreateView.as_view(), name="alert_create"),
    path("alerts/<int:pk>/", views_alerts.AlertUpdateView.as_view(), name="alert_edit"),
    path("alerts/<int:pk>/delete/", views_alerts.AlertDeleteView.as_view(), name="alert_delete"),
    path("reports/new/", views_alerts.ReportCreateView.as_view(), name="report_create"),
    path("reports/<int:pk>/", views_alerts.ReportUpdateView.as_view(), name="report_edit"),
    # Budgets
    path("budgets/", views_budgets.BudgetListView.as_view(), name="budgets"),
    path("budgets/new/", views_budgets.BudgetCreateView.as_view(), name="budget_create"),
    path("budgets/<int:pk>/", views_budgets.BudgetUpdateView.as_view(), name="budget_edit"),
    path("budgets/<int:pk>/delete/", views_budgets.BudgetDeleteView.as_view(), name="budget_delete"),
    # Imports
    path("imports/", views_imports.ImportListView.as_view(), name="imports"),
    path("imports/schemas/", views_imports.ImportSchemaView.as_view(), name="import_schemas"),
    path("imports/new/", views_imports.ImportUploadView.as_view(), name="import_upload"),
    path("imports/<int:pk>/columns/", views_imports.ImportMapView.as_view(), name="import_map"),
    path("imports/<int:pk>/review/", views_imports.ImportPreviewView.as_view(), name="import_preview"),
    # Auth
    path("login/", views_auth.FinanceLoginView.as_view(), name="login"),
    path("logout/", views_auth.FinanceLogoutView.as_view(), name="logout"),
    path("two-factor/setup/", views_auth.OTPSetupView.as_view(), name="otp_setup"),
    path("two-factor/", views_auth.OTPVerifyView.as_view(), name="otp_verify"),
]
