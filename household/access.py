"""Access control for Mays Household — every private page, finance included.

Three gates, in order, and the order matters:

1. Authenticated at all?
2. A member of the household (the `household` group)?
3. Cleared the second factor in this session?

The first two failures render the same 403 for anyone who has no business
here. It is deliberately not a redirect to a login page: a stranger poking at
/finance or /household should not learn that a login form exists, nor what it
protects. The
third failure *is* a redirect — by then the visitor has proven they hold a
household account, so guiding them through TOTP leaks nothing.

This lived in `finance/access.py` until finance became one section of the
household shell (ADR 0008). The group was renamed from `finance` to
`household` by `household/migrations/0001_rename_member_group.py`.
"""

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import urlencode

HOUSEHOLD_GROUP = "household"


def is_household_member(user) -> bool:
    return user.is_authenticated and user.groups.filter(name=HOUSEHOLD_GROUP).exists()


class HouseholdMemberMixin:
    """Gates 1 and 2 only.

    For the auth screens themselves, which an authenticated member must reach
    precisely because they have not cleared the second factor yet.
    """

    def dispatch(self, request, *args, **kwargs):
        if not is_household_member(request.user):
            raise PermissionDenied

        return super().dispatch(request, *args, **kwargs)


class HouseholdAccessMixin:
    """All three gates — the base of every private page in every section."""

    def dispatch(self, request, *args, **kwargs):
        if not is_household_member(request.user):
            raise PermissionDenied

        if not request.user.is_verified():
            return redirect(self._second_factor_url(request))

        return super().dispatch(request, *args, **kwargs)

    @staticmethod
    def _second_factor_url(request):
        from django_otp.plugins.otp_totp.models import TOTPDevice

        has_device = TOTPDevice.objects.filter(
            user=request.user, confirmed=True
        ).exists()

        if not has_device:
            return reverse("household:otp_setup")

        # Carry the page that was asked for through the challenge, so signing
        # in from a bookmark lands on the bookmark. OTPVerifyView validates it
        # with safe_next() before honoring it, like every other `next`.
        return f"{reverse('household:otp_verify')}?{urlencode({'next': request.get_full_path()})}"
