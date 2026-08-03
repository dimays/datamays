from django.urls import path

from . import views, views_auth

app_name = "finance"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("transactions/", views.TransactionsView.as_view(), name="transactions"),
    path("spend/", views.SpendView.as_view(), name="spend"),
    path("income/", views.IncomeView.as_view(), name="income"),
    path("savings/", views.SavingsView.as_view(), name="savings"),
    path("settings/", views.SettingsView.as_view(), name="settings"),
    path("preferences/", views.PreferencesView.as_view(), name="preferences"),
    # Auth
    path("login/", views_auth.FinanceLoginView.as_view(), name="login"),
    path("logout/", views_auth.FinanceLogoutView.as_view(), name="logout"),
    path("two-factor/setup/", views_auth.OTPSetupView.as_view(), name="otp_setup"),
    path("two-factor/", views_auth.OTPVerifyView.as_view(), name="otp_verify"),
]
