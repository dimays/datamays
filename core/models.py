# core/models.py
from django.db import models
from django.urls import reverse
from django.utils.text import slugify
from django.utils import timezone
import markdown
import math


class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=60, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Post(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)

    summary = models.TextField(
        help_text="Short description shown on the writings index page"
    )

    content = models.TextField(help_text="Markdown content")
    content_html = models.TextField(editable=False)

    tags = models.ManyToManyField(Tag, related_name="posts", blank=True)

    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_at"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)

        self.content_html = markdown.markdown(
            self.content,
            extensions=[
                "fenced_code",
                "codehilite",
                "tables",
                "toc",
            ],
        )

        super().save(*args, **kwargs)

    def publish(self):
        if self.published_at is None:
            self.published_at = timezone.now()
            self.save(update_fields=["published_at"])

    def unpublish(self):
        self.published_at = None
        self.save(update_fields=["published_at"])

    @property
    def reading_time(self):
        word_count = len(self.content.split())
        return max(1, math.ceil(word_count / 200))

    def get_absolute_url(self):
        return reverse("core:writing_detail", args=[self.slug])


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
