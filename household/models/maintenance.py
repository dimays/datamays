"""Home maintenance: the shared upkeep a house needs on a schedule.

A **maintenance item** is the definition — what, where, how, the supplies,
what it usually costs. Its schedule and whose list it lands on live on the
one household-owned **chore** it owns, so maintenance appears on Today and
on the checklists with no special-casing, and every rule about due dates,
missing, and overdue is the chores' rules (see docs/scheduling.md).

Completing a maintenance occurrence can record what it cost; the finance
bridge phase links that to the real transaction.
"""

from django.core.validators import MinValueValidator
from django.db import models

from .base import TimestampedModel, money_field
from .chores import Chore


class MaintenanceArea(models.TextChoices):
    HVAC = "hvac", "Heating & cooling"
    PLUMBING = "plumbing", "Plumbing & water"
    ELECTRICAL = "electrical", "Electrical"
    SAFETY = "safety", "Safety"
    APPLIANCES = "appliances", "Appliances"
    EXTERIOR = "exterior", "Exterior & roof"
    YARD = "yard", "Yard & garden"
    CLEANING = "cleaning", "Deep cleaning"
    OTHER = "other", "Other"


class MaintenanceItem(TimestampedModel):
    chore = models.OneToOneField(
        Chore,
        on_delete=models.CASCADE,
        related_name="maintenance_item",
        help_text="Carries the schedule, whose list it's on, and the history.",
    )

    area = models.CharField(max_length=20, choices=MaintenanceArea.choices, default=MaintenanceArea.OTHER)
    location = models.CharField(max_length=120, blank=True, help_text="Where in the house — \"basement furnace\".")
    instructions = models.TextField(blank=True, help_text="How to do it, for whichever of you does it next.")
    supplies = models.TextField(blank=True, help_text="What it needs — \"16x25x1 MERV 11 filter\".")
    supply_url = models.URLField(blank=True, help_text="Where to buy them.")
    estimated_cost = money_field(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="What it usually costs each time, as a positive number.",
    )

    class Meta:
        ordering = ["area", "chore__title"]

    def __str__(self):
        return self.chore.title

    @property
    def name(self):
        return self.chore.title
