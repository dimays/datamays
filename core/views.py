from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.http import require_GET
from django.views.generic import TemplateView, ListView, DetailView
from django.shortcuts import get_object_or_404
from .models import Project, Tag, Post
from datetime import datetime


def published_post_slugs():
    """The slugs a project's "Read the story" link may point at. A project can
    name its write-up while the post is still a draft; linking it then would
    be a 404. One query, however many projects are on the page."""
    return set(Post.objects.filter(published_at__isnull=False).values_list("slug", flat=True))


@require_GET
def robots_txt(request):
    # Nothing is disallowed. The private apps answer strangers with a 403
    # and aren't linked from anywhere public; listing /finance/ or
    # /household/ here would only tell people they exist.
    lines = [
        "User-agent: *",
        "Allow: /",
        "",
        f"Sitemap: {settings.SITE_URL}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain")


class HomeView(TemplateView):
    template_name = "core/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["featured_projects"] = (
            Project.objects.filter(is_featured=True, is_public=True)
            .order_by("priority", "-created_at")[:3]
        )
        context["published_post_slugs"] = published_post_slugs()
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["published_post_slugs"] = published_post_slugs()
        return context


class ProjectDetailView(DetailView):
    model = Project
    template_name = "core/project_detail.html"
    context_object_name = "project"

    def get_queryset(self):
        # A hidden project is a draft: its owner can read it, nobody else
        # (and no search engine) can find it.
        if self.request.user.is_staff:
            return Project.objects.all()
        return Project.objects.filter(is_public=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["published_post_slugs"] = published_post_slugs()
        return context


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
        context["active_tag_name"] = next(
            (t.name for t in context["tags"] if t.slug == context["active_tag"]), ""
        )

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