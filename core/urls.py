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
    path("writings/", views.WritingListView.as_view(), name="writings_list"),
    path(
        "writings/tag/<slug:tag_slug>/",
        views.WritingListView.as_view(),
        name="writings_by_tag",
    ),
    path(
        "writings/<slug:slug>/",
        views.WritingDetailView.as_view(),
        name="writing_detail",
    ),
    path("styleguide/", views.StyleguideView.as_view(), name="styleguide"),
]

