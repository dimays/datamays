"""Access control for the finance app.

Three gates, in order, and the order matters:

1. Authenticated at all?
2. A member of the household (the `finance` group)?
3. Cleared the second factor in this session?

The first two failures render the same 403 for anyone who has no business
here. It is deliberately not a redirect to a login page: a stranger poking at
/finance should not learn that a login form exists, nor what it protects. The
third failure *is* a redirect — by then the visitor has proven they hold a
household account, so guiding them through TOTP leaks nothing.
"""

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse

FINANCE_GROUP = "finance"


def is_household_member(user) -> bool:
    return user.is_authenticated and user.groups.filter(name=FINANCE_GROUP).exists()


class HouseholdMemberMixin:
    """Gates 1 and 2 only.

    For the auth screens themselves, which an authenticated member must reach
    precisely because they have not cleared the second factor yet.
    """

    def dispatch(self, request, *args, **kwargs):
        if not is_household_member(request.user):
            raise PermissionDenied

        return super().dispatch(request, *args, **kwargs)


class FinanceAccessMixin:
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

        return reverse("finance:otp_verify" if has_device else "finance:otp_setup")
