from django.urls import path

from . import views

app_name = "household"

urlpatterns = [
    path("", views.TodayView.as_view(), name="today"),
    # Sign-in
    path("login/", views.HouseholdLoginView.as_view(), name="login"),
    path("logout/", views.HouseholdLogoutView.as_view(), name="logout"),
    path("two-factor/setup/", views.OTPSetupView.as_view(), name="otp_setup"),
    path("two-factor/", views.OTPVerifyView.as_view(), name="otp_verify"),
]
