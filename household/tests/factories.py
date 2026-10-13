"""Builders shared by every section's tests."""

from django.contrib.auth.models import Group, User
from django_otp.plugins.otp_totp.models import TOTPDevice

from household.access import HOUSEHOLD_GROUP

PASSWORD = "a-long-enough-test-password"


def make_member(username, *, in_group=True, with_device=False, **kwargs):
    """A user, by default a household member; optionally with an authenticator."""
    user = User.objects.create_user(username=username, password=PASSWORD, **kwargs)

    if in_group:
        group, _ = Group.objects.get_or_create(name=HOUSEHOLD_GROUP)
        user.groups.add(group)

    if with_device:
        TOTPDevice.objects.create(user=user, name="test", confirmed=True)

    return user


def sign_in(client, user):
    """A fully verified session: password and second factor both cleared.

    Mirrors what OTPSetupView/OTPVerifyView do on a correct code, so a test
    about a screen doesn't have to replay the sign-in flow to reach it.
    """
    if not TOTPDevice.objects.filter(user=user, confirmed=True).exists():
        TOTPDevice.objects.create(user=user, name="test", confirmed=True)

    client.force_login(user)
    session = client.session
    session["otp_device_id"] = TOTPDevice.objects.get(user=user, confirmed=True).persistent_id
    session.save()


def make_chore(owner=None, *, start=True, today=None, **kwargs):
    """A chore, with its first occurrence opened as the app would.

    `owner=None` makes a household-owned chore. Personal chores default to
    their owner as assignee, the same as creating one from the checklist.
    """
    from household.models import Chore
    from household.services import occurrences

    kwargs.setdefault("title", "Take out the bins")
    if owner is not None:
        kwargs.setdefault("assignee", owner)

    chore = Chore.objects.create(owner=owner, **kwargs)
    if start:
        occurrences.reschedule(chore, today=today)
    return chore
