from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("transactions/", views.TransactionsView.as_view(), name="transactions"),
    path("spend/", views.SpendView.as_view(), name="spend"),
    path("income/", views.IncomeView.as_view(), name="income"),
    path("savings/", views.SavingsView.as_view(), name="savings"),
    path("settings/", views.SettingsView.as_view(), name="settings"),
    path("preferences/", views.PreferencesView.as_view(), name="preferences"),
]
