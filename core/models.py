# core/models.py
from django.db import models
from django.urls import reverse
from django.utils.text import slugify
from django.utils import timezone
import markdown
import math


def render_markdown(text):
    return markdown.markdown(
        text,
        extensions=[
            "fenced_code",
            "codehilite",
            "tables",
            "toc",
        ],
    )


# Where a page's picture can live: a full URL on another site (a project's
# own preview card), or a path on this one (/static/img/...). A URLField
# would refuse the second.
def image_url_field():
    return models.CharField(
        max_length=500,
        blank=True,
        help_text="Full URL, or a path on this site such as /static/img/projects/x.webp. "
        "Used at the top of the page and as its preview card when shared; 1200×630 is best.",
    )


def image_alt_field():
    return models.CharField(
        max_length=300,
        blank=True,
        help_text="What the picture shows, for screen readers and search engines.",
    )


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

    image_url = image_url_field()
    image_alt = image_alt_field()

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

        self.content_html = render_markdown(self.content)

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
    overview = models.TextField(
        blank=True,
        help_text="[Markdown] What it is and who it's for. Shown first, before the story.",
    )
    motivation = models.TextField(
        blank=True,
        help_text="[Markdown] Why this project exists. What problem or curiosity drove it?",
    )
    expected_outcome = models.TextField(
        blank=True,
        help_text="[Markdown] What I expected the outcome of this project to be. What did I hope to accomplish?",
    )
    challenges = models.TextField(
        blank=True,
        help_text="[Markdown] Key technical or conceptual challenges encountered.",
    )
    how_its_built = models.TextField(
        blank=True,
        help_text="[Markdown] How it's built, and what's notable technically.",
    )
    lessons_learned = models.TextField(
        blank=True,
        help_text="[Markdown] What I'd do differently, or what this taught me.",
    )
    overview_html = models.TextField(editable=False, default="")
    how_its_built_html = models.TextField(editable=False, default="")
    motivation_html = models.TextField(editable=False, default='fallback-value')
    expected_outcome_html = models.TextField(editable=False, default='fallback-value')
    challenges_html = models.TextField(editable=False, default='fallback-value')
    lessons_learned_html = models.TextField(editable=False, default='fallback-value')

    image_url = image_url_field()
    image_alt = image_alt_field()

    # --- Practical details ---
    tech_stack = models.CharField(
        max_length=300,
        blank=True,
        help_text="Comma-separated list (e.g. Django, Postgres, dbt, AWS).",
    )
    repo_url = models.URLField(blank=True)
    live_url = models.URLField(blank=True)
    blog_post_slug = models.TextField(
        blank=True,
        help_text="Optional deep-dive writeup (use slug from post)",
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

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)

        self.overview_html = render_markdown(self.overview)
        self.motivation_html = render_markdown(self.motivation)
        self.expected_outcome_html = render_markdown(self.expected_outcome)
        self.challenges_html = render_markdown(self.challenges)
        self.how_its_built_html = render_markdown(self.how_its_built)
        self.lessons_learned_html = render_markdown(self.lessons_learned)

        super().save(*args, **kwargs)
    
    @property
    def tech_stack_list(self):
        return [t.strip() for t in self.tech_stack.split(",") if t.strip()]

    @property
    def blog_post_url(self):
        if self.blog_post_slug:
            return reverse("core:writing_detail", kwargs={"slug": self.blog_post_slug})
        return None