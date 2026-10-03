"""Projects: longer-term shared efforts — a kitchen refresh, a garden.

A project has milestones on a timeline, links to the documents that live
elsewhere (Drive, quotes), and a running log of notes and decisions. Its
**tasks are chores** with `Chore.project` set: household-owned, so both of
you manage them, and assigning one puts it on that person's checklist and
Today. That is the whole mechanism behind "tasks become chores".

Budget lines and linked spending arrive with the finance bridge.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from .base import TimestampedModel, money_field


class ProjectStatus(models.TextChoices):
    ACTIVE = "active", "In progress"
    PLANNED = "planned", "Planned"
    IDEA = "idea", "Idea"
    ON_HOLD = "on_hold", "On hold"
    DONE = "done", "Done"


# The order the project list groups by: what's moving first.
STATUS_ORDER = [
    ProjectStatus.ACTIVE, ProjectStatus.PLANNED, ProjectStatus.IDEA,
    ProjectStatus.ON_HOLD, ProjectStatus.DONE,
]


# A project's tasks are on people's lists only while it is under way or
# planned. On hold, done, or still an idea, they drop off every checklist,
# Today, the badge, and the digest — and come back if it resumes. (Decided
# with David, 2026-10-02.)
LISTED_PROJECT_STATUSES = (ProjectStatus.ACTIVE, ProjectStatus.PLANNED)


class Project(TimestampedModel):
    name = models.CharField(max_length=160)
    summary = models.TextField(blank=True, help_text="What it is and why — a sentence or two.")
    status = models.CharField(max_length=10, choices=ProjectStatus.choices, default=ProjectStatus.PLANNED)

    @property
    def tasks_are_listed(self):
        return self.status in LISTED_PROJECT_STATUSES
    start_on = models.DateField(null=True, blank=True)
    target_on = models.DateField(null=True, blank=True, help_text="When you'd like it done.")
    budget_total = money_field(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="The overall budget, as a positive number.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        if self.start_on and self.target_on and self.target_on < self.start_on:
            raise ValidationError({"target_on": "The target is before the start."})


class Milestone(TimestampedModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="milestones")
    name = models.CharField(max_length=160)
    target_on = models.DateField(null=True, blank=True)
    completed_on = models.DateField(null=True, blank=True)

    class Meta:
        # Dated milestones in date order, undated ones after them in the order
        # they were added. Explicit about NULLs for the same reason as
        # Occurrence: SQLite and Postgres disagree by default.
        ordering = [models.F("target_on").asc(nulls_last=True), "id"]

    def __str__(self):
        return self.name

    @property
    def is_done(self):
        return self.completed_on is not None

    def is_late(self, today):
        return not self.is_done and self.target_on is not None and self.target_on < today


class ProjectLink(TimestampedModel):
    """A document that lives elsewhere — a Drive folder, a quote, a mood board."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="links")
    title = models.CharField(max_length=160)
    url = models.URLField(max_length=1000)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title


class ProjectNote(TimestampedModel):
    """One entry in the project's running log of notes and decisions."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    body = models.TextField()

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.body[:60]
