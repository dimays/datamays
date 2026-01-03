from django.urls import path
from . import views

app_name = "core"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("about/", views.AboutView.as_view(), name="about"),
    path("projects/", views.ProjectListView.as_view(), name="projects_list"),
    path(
        "projects/<slug:slug>/",
        views.ProjectDetailView.as_view(),
        name="project_detail",
    ),
    path("styleguide/", views.StyleguideView.as_view(), name="styleguide"),
]
