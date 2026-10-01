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
    # Upkeep (maintenance)
    path("upkeep/", views.UpkeepListView.as_view(), name="upkeep"),
    path("upkeep/new/", views.UpkeepCreateView.as_view(), name="upkeep_create"),
    path("upkeep/starter/", views.LibraryView.as_view(), name="upkeep_library"),
    path("upkeep/starter/<slug:key>/", views.LibraryAdoptView.as_view(), name="upkeep_adopt"),
    path("upkeep/<int:pk>/", views.UpkeepDetailView.as_view(), name="upkeep_detail"),
    path("upkeep/<int:pk>/edit/", views.UpkeepUpdateView.as_view(), name="upkeep_edit"),
    path("upkeep/<int:pk>/delete/", views.UpkeepDeleteView.as_view(), name="upkeep_delete"),
    path("preferences/", views.HouseholdPreferencesView.as_view(), name="preferences"),
    # Sign-in
    path("login/", views.HouseholdLoginView.as_view(), name="login"),
    path("logout/", views.HouseholdLogoutView.as_view(), name="logout"),
    path("two-factor/setup/", views.OTPSetupView.as_view(), name="otp_setup"),
    path("two-factor/", views.OTPVerifyView.as_view(), name="otp_verify"),
]
