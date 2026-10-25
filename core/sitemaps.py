from django.conf import settings
from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Post, Project


class CanonicalSitemap(Sitemap):
    """Every address on www.datamays.com, whichever host asked: Django would
    otherwise use the request's host, and the herokuapp.com name answers too."""

    protocol = "https"

    def get_domain(self, site=None):
        return settings.SITE_URL.split("://", 1)[1]


class PageSitemap(CanonicalSitemap):
    # The styleguide is left out on purpose: it's a reference for the
    # design tokens, not something to find in a search.
    def items(self):
        return ["core:home", "core:about", "core:projects_list", "core:writings_list", "contact:contact"]

    def location(self, item):
        return reverse(item)


class ProjectSitemap(CanonicalSitemap):
    def items(self):
        return Project.objects.filter(is_public=True).order_by("priority", "-created_at")

    def lastmod(self, project):
        return project.updated_at


class PostSitemap(CanonicalSitemap):
    def items(self):
        return Post.objects.filter(published_at__isnull=False)

    def lastmod(self, post):
        return max(post.updated_at, post.published_at)


SITEMAPS = {"pages": PageSitemap, "projects": ProjectSitemap, "writing": PostSitemap}
