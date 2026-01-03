from django.views.generic import TemplateView, ListView, DetailView
from .models import Project
from datetime import datetime


class HomeView(TemplateView):
    template_name = "core/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["featured_projects"] = (
            Project.objects.filter(is_featured=True, is_public=True)
            .order_by("priority", "-created_at")[:3]
        )
        return context


class AboutView(TemplateView):
    template_name = "core/about.html"


class ProjectListView(ListView):
    model = Project
    template_name = "core/projects.html"
    context_object_name = "projects"

    def get_queryset(self):
        return (
            Project.objects.filter(is_public=True)
            .order_by("priority", "-created_at")
        )


class ProjectDetailView(DetailView):
    model = Project
    template_name = "core/project_detail.html"
    context_object_name = "project"


class StyleguideView(TemplateView):
    template_name = "core/styleguide.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["year"] = datetime.now().year
        return context