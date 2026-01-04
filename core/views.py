from django.views.generic import TemplateView, ListView, DetailView
from django.shortcuts import get_object_or_404
from .models import Project, Tag, Post
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


class WritingListView(ListView):
    model = Post
    template_name = "core/writings.html"
    context_object_name = "posts"
    paginate_by = 10

    def get_queryset(self):
        queryset = Post.objects.filter(published_at__isnull=False)

        tag_slug = self.kwargs.get("tag_slug")
        if tag_slug:
            queryset = queryset.filter(tags__slug=tag_slug)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["tags"] = Tag.objects.all()
        context["active_tag"] = self.kwargs.get("tag_slug")

        return context


class WritingDetailView(DetailView):
    model = Post
    template_name = "core/writing_detail.html"
    context_object_name = "post"

    def get_queryset(self):
        return Post.objects.filter(published_at__isnull=False)

    def get_object(self, queryset=None):
        return get_object_or_404(
            self.get_queryset(),
            slug=self.kwargs["slug"],
        )


class StyleguideView(TemplateView):
    template_name = "core/styleguide.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["year"] = datetime.now().year
        return context