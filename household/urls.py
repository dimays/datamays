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
    # Projects
    path("projects/", views.ProjectListView.as_view(), name="projects"),
    path("projects/new/", views.ProjectCreateView.as_view(), name="project_create"),
    path("projects/<int:pk>/", views.ProjectDetailView.as_view(), name="project_detail"),
    path("projects/<int:pk>/edit/", views.ProjectUpdateView.as_view(), name="project_edit"),
    path("projects/<int:pk>/delete/", views.ProjectDeleteView.as_view(), name="project_delete"),
    path("projects/<int:pk>/milestones/new/", views.MilestoneCreateView.as_view(), name="milestone_create"),
    path("projects/<int:pk>/milestones/<int:milestone_pk>/", views.MilestoneUpdateView.as_view(), name="milestone_edit"),
    path("projects/<int:pk>/milestones/<int:milestone_pk>/toggle/", views.MilestoneToggleView.as_view(), name="milestone_toggle"),
    path("projects/<int:pk>/milestones/<int:milestone_pk>/delete/", views.MilestoneDeleteView.as_view(), name="milestone_delete"),
    path("projects/<int:pk>/links/new/", views.LinkCreateView.as_view(), name="link_create"),
    path("projects/<int:pk>/links/<int:link_pk>/delete/", views.LinkDeleteView.as_view(), name="link_delete"),
    path("projects/<int:pk>/notes/new/", views.NoteCreateView.as_view(), name="note_create"),
    path("projects/<int:pk>/notes/<int:note_pk>/delete/", views.NoteDeleteView.as_view(), name="note_delete"),
    path("projects/<int:pk>/budget/lines/new/", views.BudgetLineCreateView.as_view(), name="budget_line_create"),
    path("projects/<int:pk>/budget/lines/<int:line_pk>/delete/", views.BudgetLineDeleteView.as_view(), name="budget_line_delete"),
    path("projects/<int:pk>/spending/", views.ProjectSpendingView.as_view(), name="project_spending"),
    path("projects/<int:pk>/spending/<int:expense_pk>/", views.ExpenseUpdateView.as_view(), name="expense_edit"),
    path("projects/<int:pk>/spending/<int:expense_pk>/delete/", views.ExpenseDeleteView.as_view(), name="expense_delete"),
    path("projects/<int:pk>/tasks/new/", views.TaskCreateView.as_view(), name="project_task_create"),
    path("projects/<int:pk>/tasks/<int:task_pk>/edit/", views.TaskUpdateView.as_view(), name="project_task_edit"),
    # Upkeep (maintenance)
    path("upkeep/", views.UpkeepListView.as_view(), name="upkeep"),
    path("upkeep/new/", views.UpkeepCreateView.as_view(), name="upkeep_create"),
    path("upkeep/starter/", views.LibraryView.as_view(), name="upkeep_library"),
    path("upkeep/starter/<slug:key>/", views.LibraryAdoptView.as_view(), name="upkeep_adopt"),
    path("upkeep/<int:pk>/", views.UpkeepDetailView.as_view(), name="upkeep_detail"),
    path("upkeep/<int:pk>/edit/", views.UpkeepUpdateView.as_view(), name="upkeep_edit"),
    path("upkeep/<int:pk>/jobs/<int:occurrence_pk>/purchase/", views.JobLinkView.as_view(), name="job_link"),
    path("upkeep/<int:pk>/delete/", views.UpkeepDeleteView.as_view(), name="upkeep_delete"),
    path("preferences/", views.HouseholdPreferencesView.as_view(), name="preferences"),
    path("help/", views.HelpView.as_view(), name="help"),
    # Sign-in
    path("login/", views.HouseholdLoginView.as_view(), name="login"),
    path("logout/", views.HouseholdLogoutView.as_view(), name="logout"),
    path("two-factor/setup/", views.OTPSetupView.as_view(), name="otp_setup"),
    path("two-factor/", views.OTPVerifyView.as_view(), name="otp_verify"),
]
