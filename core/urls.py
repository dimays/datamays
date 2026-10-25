from django.contrib.sitemaps.views import sitemap
from django.urls import path
from . import views
from .sitemaps import SITEMAPS

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
    path("writing/", views.WritingListView.as_view(), name="writings_list"),
    path(
        "writing/tag/<slug:tag_slug>/",
        views.WritingListView.as_view(),
        name="writings_by_tag",
    ),
    path(
        "writing/<slug:slug>/",
        views.WritingDetailView.as_view(),
        name="writing_detail",
    ),
    path("styleguide/", views.StyleguideView.as_view(), name="styleguide"),
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path("sitemap.xml", sitemap, {"sitemaps": SITEMAPS}, name="sitemap"),
]

