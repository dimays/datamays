from django.urls import path

from . import views

app_name = "household"

urlpatterns = [
    path("", views.TodayView.as_view(), name="today"),
    # Chores
    path("chores/", views.ChecklistView.as_view(), name="chores"),
    path("chores/all/", views.ChoreListView.as_view(), name="chore_list"),
    path("chores/new/", views.ChoreCreateView.as_view(), name="chore_create"),
    path("chores/preview/", views.SchedulePreviewView.as_view(), name="chore_preview"),
    path("chores/partner/", views.PartnerToggleView.as_view(), name="chores_partner_toggle"),
    path("chores/<int:pk>/", views.ChoreDetailView.as_view(), name="chore_detail"),
    path("chores/<int:pk>/edit/", views.ChoreUpdateView.as_view(), name="chore_edit"),
    path("chores/<int:pk>/delete/", views.ChoreDeleteView.as_view(), name="chore_delete"),
    path(
        "occurrences/<int:pk>/<str:action>/",
        views.OccurrenceActionView.as_view(),
        name="occurrence_action",
    ),
    path("preferences/", views.HouseholdPreferencesView.as_view(), name="preferences"),
    # Sign-in
    path("login/", views.HouseholdLoginView.as_view(), name="login"),
    path("logout/", views.HouseholdLogoutView.as_view(), name="logout"),
    path("two-factor/setup/", views.OTPSetupView.as_view(), name="otp_setup"),
    path("two-factor/", views.OTPVerifyView.as_view(), name="otp_verify"),
]
