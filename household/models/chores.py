"""Chores and their occurrences.

A **chore** is anything on someone's checklist, one-off or repeating. It is
the universal unit of "a thing to do": maintenance items and project tasks
arrive later as chores with a link back to where they came from.

An **occurrence** is one dated instance of a chore — this week's bins, the
filter change due in March. A chore has at most one *open* occurrence at a
time, enforced by a database constraint; completing, skipping, or missing it
is what opens the next. See `household/services/occurrences.py` for that
lifecycle and `household/scheduling.py` for the date arithmetic.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .. import scheduling
from ..dates import household_today, to_household_date
from ..scheduling import Anchor, Frequency, MonthlyMode
from .base import TimestampedModel, money_field

MONTH_CHOICES = [
    (1, "January"), (2, "February"), (3, "March"), (4, "April"),
    (5, "May"), (6, "June"), (7, "July"), (8, "August"),
    (9, "September"), (10, "October"), (11, "November"), (12, "December"),
]


class Chore(TimestampedModel):
    title = models.CharField(max_length=160)
    notes = models.TextField(blank=True)

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="owned_chores",
        help_text=(
            "Who controls it. Empty means the household owns it — shared "
            "work either of you can manage."
        ),
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_chores",
        help_text="Whose checklist it appears on. Empty means either of you.",
    )
    others_can_manage = models.BooleanField(
        default=False,
        help_text="Let the other person edit, skip, or delete this chore too.",
    )

    # The schedule. See household/scheduling.py for what each field means;
    # `schedule` below assembles them.
    frequency = models.CharField(max_length=10, choices=Frequency.choices, default=Frequency.ONCE)
    starts_on = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "For a one-off, when it's due (blank for whenever). For a repeating "
            "chore, the first due date — which also sets the weekday or day of "
            "the month it repeats on."
        ),
    )
    interval = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])
    weekdays = models.JSONField(
        default=list, blank=True, help_text="Weekly only: 0 = Monday … 6 = Sunday."
    )
    monthly_mode = models.CharField(max_length=15, choices=MonthlyMode.choices, default=MonthlyMode.DAY)
    anchor = models.CharField(max_length=20, choices=Anchor.choices, default=Anchor.FIXED)
    ends_on = models.DateField(null=True, blank=True)
    max_occurrences = models.PositiveSmallIntegerField(null=True, blank=True)
    deadline = models.DateField(
        null=True, blank=True, help_text="One-off only: the hard 'must be done by'."
    )
    deadline_offset_days = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Repeating only: each occurrence must be done within this many days of its due date.",
    )
    season_start_month = models.PositiveSmallIntegerField(
        null=True, blank=True, choices=MONTH_CHOICES, validators=[MaxValueValidator(12)]
    )
    season_end_month = models.PositiveSmallIntegerField(
        null=True, blank=True, choices=MONTH_CHOICES, validators=[MaxValueValidator(12)]
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title

    @property
    def schedule(self) -> scheduling.Schedule:
        season = None
        if self.season_start_month and self.season_end_month:
            season = (self.season_start_month, self.season_end_month)

        return scheduling.Schedule(
            frequency=self.frequency,
            starts_on=self.starts_on,
            interval=self.interval,
            weekdays=tuple(self.weekdays or ()),
            monthly_mode=self.monthly_mode,
            anchor=self.anchor,
            ends_on=self.ends_on,
            max_occurrences=self.max_occurrences,
            deadline_offset_days=self.deadline_offset_days,
            season=season,
            # An unsaved chore (the form's live preview) counts from today.
            counts_from=to_household_date(self.created_at) if self.created_at else household_today(),
        )

    @property
    def repeats(self):
        return self.frequency != Frequency.ONCE

    @property
    def is_household_owned(self):
        return self.owner_id is None

    @property
    def is_maintenance(self):
        # Callers that loop over chores select_related("maintenance_item"),
        # so this reads a cached relation rather than querying per chore.
        try:
            return self.maintenance_item is not None
        except Chore.maintenance_item.RelatedObjectDoesNotExist:
            return False

    def get_absolute_url(self):
        from django.urls import reverse

        if self.is_maintenance:
            return reverse("household:upkeep_detail", args=[self.maintenance_item.pk])
        return reverse("household:chore_detail", args=[self.pk])

    def describe_schedule(self):
        return scheduling.describe(self.schedule)

    def clean(self):
        errors = scheduling.validate(self.schedule)

        if bool(self.season_start_month) != bool(self.season_end_month):
            errors["season_start_month"] = "Pick both the month the season opens and the month it closes."
        if self.repeats and self.deadline:
            errors["deadline"] = (
                "A repeating chore's deadline is set per occurrence — use "
                "'days to finish' instead."
            )
        if not self.repeats and self.deadline_offset_days is not None:
            errors["deadline_offset_days"] = "Only a repeating chore has a deadline per occurrence."
        if not self.repeats and self.deadline and self.starts_on and self.deadline < self.starts_on:
            errors["deadline"] = "The deadline is before the due date."

        if errors:
            raise ValidationError(errors)


class OccurrenceStatus(models.TextChoices):
    OPEN = "open", "To do"
    DONE = "done", "Done"
    SKIPPED = "skipped", "Skipped"
    MISSED = "missed", "Missed"


class Occurrence(TimestampedModel):
    chore = models.ForeignKey(Chore, on_delete=models.CASCADE, related_name="occurrences")

    due_on = models.DateField(null=True, blank=True, help_text="Empty for a one-off due whenever.")
    deadline = models.DateField(null=True, blank=True)

    status = models.CharField(max_length=10, choices=OccurrenceStatus.choices, default=OccurrenceStatus.OPEN)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="completed_occurrences",
        help_text="Who actually did it — not necessarily the assignee.",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)
    cost = money_field(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="What doing it cost, as a positive number — mostly for maintenance.",
    )

    class Meta:
        # Explicit about undated one-offs: SQLite sorts NULL first and
        # Postgres last, so the local server and production would otherwise
        # disagree about where "whenever" chores go.
        ordering = [models.F("due_on").asc(nulls_last=True), "id"]
        constraints = [
            # The lifecycle depends on this. Without it, a double tap on
            # "done" could open two next occurrences, and the chore would
            # appear twice on a checklist forever after.
            models.UniqueConstraint(
                fields=["chore"],
                condition=models.Q(status="open"),
                name="one_open_occurrence_per_chore",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "due_on"]),
        ]

    def __str__(self):
        return f"{self.chore} ({self.due_on or 'whenever'})"

    @property
    def is_open(self):
        return self.status == OccurrenceStatus.OPEN

    def effective_deadline(self):
        """The date after which this is overdue: the deadline if there is
        one, otherwise the due date itself."""
        return self.deadline or self.due_on

    def is_overdue(self, today):
        effective = self.effective_deadline()
        return self.is_open and effective is not None and effective < today

    def days_overdue(self, today):
        return (today - self.effective_deadline()).days if self.is_overdue(today) else 0
