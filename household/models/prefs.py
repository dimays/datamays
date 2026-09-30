from django.conf import settings
from django.db import models

from .base import TimestampedModel


class HouseholdPreference(TimestampedModel):
    """Per-person settings for the household sections.

    Finance keeps its own (`finance.UserPreference`) — homepage widgets,
    chart order — because those are finance's business, not the shell's.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="household_preferences",
    )
    show_partner_chores = models.BooleanField(
        default=False,
        help_text="Show the other person's chores alongside your own.",
    )
    share_new_chores = models.BooleanField(
        default=False,
        help_text="Let the other person manage new chores you create, unless you say otherwise.",
    )

    def __str__(self):
        return f"Household preferences for {self.user}"

    @classmethod
    def for_user(cls, user):
        preference, _ = cls.objects.get_or_create(user=user)
        return preference
