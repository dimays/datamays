# core/models.py
from django.db import models
from django.urls import reverse


class Project(models.Model):
    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        IN_PROGRESS = "in_progress", "In Progress"
        IN_PRODUCTION = "in_production", "In Production"
        ARCHIVED = "archived", "Archived"
        CANCELLED = "cancelled", "Cancelled"

    # --- Core identity ---
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    short_description = models.TextField(
        help_text="One-two sentence summary shown on overview pages."
    )

    # --- Narrative sections ---
    motivation = models.TextField(
        blank=True,
        help_text="Why this project exists. What problem or curiosity drove it?",
    )
    expected_outcome = models.TextField(
        blank=True,
        help_text="What I expected the outcome of this project to be. What did I hope to accomplish?",
    )
    challenges = models.TextField(
        blank=True,
        help_text="Key technical or conceptual challenges encountered.",
    )
    lessons_learned = models.TextField(
        blank=True,
        help_text="What I'd do differently, or what this taught me.",
    )

    # --- Practical details ---
    tech_stack = models.CharField(
        max_length=300,
        blank=True,
        help_text="Comma-separated list (e.g. Django, Postgres, dbt, AWS).",
    )
    repo_url = models.URLField(blank=True)
    live_url = models.URLField(blank=True)
    blog_post_url = models.URLField(
        blank=True,
        help_text="Optional deep-dive writeup.",
    )

    # --- Display & control ---
    status = models.CharField(
        max_length=50,
        choices=Status.choices,
        default=Status.PLANNED,
        help_text="The project's current status.",
    )
    priority = models.PositiveIntegerField(
        default=99,
        help_text="Lower values appear first.",
    )
    is_public = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)

    # --- Metadata ---
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["priority", "-created_at"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("core:project_detail", kwargs={"slug": self.slug})
