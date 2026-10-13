"""Who is in the household.

Two people, by design. Code that needs "the other person" asks here rather
than assuming a username, so nothing depends on who signed up first.
"""

from django.contrib.auth import get_user_model

from ..access import HOUSEHOLD_GROUP


def members():
    return get_user_model().objects.filter(groups__name=HOUSEHOLD_GROUP).order_by("first_name", "username")


def partner_of(user):
    """The other member, or None in a household of one (e.g. mid-setup)."""
    return members().exclude(pk=user.pk).first()


def display_name(user):
    if user is None:
        return "Either of us"
    return user.first_name or user.username
