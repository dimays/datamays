from django.db import models

from .base import TimestampedModel


class QuarterlyReport(TimestampedModel):
    """A generated snapshot of one calendar quarter's finances.

    Always the calendar quarter, never a household-anchored one like budgets
    use — "Q1" has to mean the same thing every time someone opens this
    report, including when comparing two quarters side by side.

    Numeric aggregates and comparisons are stored, not recomputed on view, so
    a QFR reads the same a year later even if categories or budgets have
    since changed. The narrative is optional: `summary` is blank when no
    OPENAI_API_KEY was configured at generation time, and the report is still
    useful without it — the metrics and comparisons stand on their own.
    """

    year = models.PositiveIntegerField()
    quarter = models.PositiveSmallIntegerField(
        choices=[(1, "Q1"), (2, "Q2"), (3, "Q3"), (4, "Q4")]
    )

    period_start = models.DateField()
    period_end = models.DateField()

    # Computed aggregates and quarter-over-quarter / year-over-year deltas —
    # see services.qfr.compute_metrics / historical_comparisons for the exact
    # shape. Kept as JSON rather than a wide set of columns because the set of
    # interesting metrics is expected to grow, and every consumer (the detail
    # template, the narrator prompt) reads it as a dict either way.
    metrics = models.JSONField(default=dict, blank=True)
    comparisons = models.JSONField(default=dict, blank=True)

    # Fixed structure, not a JSON blob: four named sections mean the detail
    # template and the narrator's prompt schema can both depend on the field
    # existing rather than parsing an open-ended shape.
    summary = models.TextField(blank=True)
    key_trends = models.TextField(blank=True)
    major_events = models.TextField(blank=True)
    risk_areas = models.TextField(blank=True)

    narrator = models.CharField(
        max_length=40,
        blank=True,
        help_text="Which narrator produced the sections above, e.g. 'openai'. Blank means none did.",
    )
    generated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-year", "-quarter"]
        constraints = [
            models.UniqueConstraint(
                fields=["year", "quarter"], name="unique_qfr_per_quarter"
            )
        ]

    def __str__(self):
        return f"Q{self.quarter} {self.year}"

    @property
    def label(self):
        return f"Q{self.quarter} {self.year}"

    @property
    def has_narrative(self):
        return bool(self.summary)
