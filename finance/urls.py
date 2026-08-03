from django.urls import path

from . import views, views_auth, views_imports

app_name = "finance"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("transactions/", views.TransactionsView.as_view(), name="transactions"),
    path("spend/", views.SpendView.as_view(), name="spend"),
    path("income/", views.IncomeView.as_view(), name="income"),
    path("savings/", views.SavingsView.as_view(), name="savings"),
    path("settings/", views.SettingsView.as_view(), name="settings"),
    path("preferences/", views.PreferencesView.as_view(), name="preferences"),
    # Imports
    path("imports/", views_imports.ImportListView.as_view(), name="imports"),
    path("imports/new/", views_imports.ImportUploadView.as_view(), name="import_upload"),
    path("imports/<int:pk>/columns/", views_imports.ImportMapView.as_view(), name="import_map"),
    path("imports/<int:pk>/review/", views_imports.ImportPreviewView.as_view(), name="import_preview"),
    # Auth
    path("login/", views_auth.FinanceLoginView.as_view(), name="login"),
    path("logout/", views_auth.FinanceLogoutView.as_view(), name="logout"),
    path("two-factor/setup/", views_auth.OTPSetupView.as_view(), name="otp_setup"),
    path("two-factor/", views_auth.OTPVerifyView.as_view(), name="otp_verify"),
]
