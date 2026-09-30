"""Sign-in, authenticator setup, and the second-factor challenge.

One sign-in for every section of Mays Household, finance included. These
moved here from `finance/views/auth.py` (ADR 0008); the old finance URLs
redirect to them.
"""

from io import BytesIO

import qrcode
import qrcode.image.svg
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils.safestring import mark_safe
from django.views.generic import FormView
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from ..access import HouseholdMemberMixin, is_household_member
from ..forms import LoginForm, OTPTokenForm
from ..redirects import safe_next
from .base import PageTitleMixin


def _qr_svg(uri: str) -> str:
    """Render an otpauth:// URI as an inline SVG.

    SVG rather than PNG so there is no Pillow dependency, and inline rather
    than a served image so the shared secret never becomes a fetchable URL.
    """
    image = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage)
    buffer = BytesIO()
    image.save(buffer)

    return mark_safe(buffer.getvalue().decode())


class HouseholdLoginView(LoginView):
    template_name = "household/login.html"
    form_class = LoginForm
    redirect_authenticated_user = True


class HouseholdLogoutView(LogoutView):
    next_page = reverse_lazy("core:home")


class OTPSetupView(PageTitleMixin, HouseholdMemberMixin, FormView):
    """One-time enrollment of an authenticator app."""

    template_name = "household/otp_setup.html"
    form_class = OTPTokenForm
    page_title = "Set up two-factor"

    def dispatch(self, request, *args, **kwargs):
        # Membership first. This check used to run before the gate, so an
        # anonymous visitor made it query devices for AnonymousUser and got a
        # 500 instead of the 403 every stranger is meant to see.
        if (
            is_household_member(request.user)
            and TOTPDevice.objects.filter(user=request.user, confirmed=True).exists()
        ):
            return redirect("household:otp_verify")

        return super().dispatch(request, *args, **kwargs)

    def get_device(self):
        # Unconfirmed devices are re-used so that reloading the page does not
        # invalidate a secret the user has already scanned.
        device, _ = TOTPDevice.objects.get_or_create(
            user=self.request.user,
            confirmed=False,
            defaults={"name": "Authenticator app"},
        )
        return device

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        device = self.get_device()

        context["qr_svg"] = _qr_svg(device.config_url)
        # Shown so a device that cannot scan can still be enrolled by hand.
        context["secret"] = device.key

        return context

    def form_valid(self, form):
        device = self.get_device()

        if not device.verify_token(form.cleaned_data["token"]):
            form.add_error(
                "token",
                "That code didn't match. Check your authenticator app and try "
                "again — codes expire every 30 seconds.",
            )
            return self.form_invalid(form)

        device.confirmed = True
        device.name = "Authenticator app"
        device.save(update_fields=["confirmed", "name"])

        otp_login(self.request, device)

        return redirect("household:today")


class OTPVerifyView(PageTitleMixin, HouseholdMemberMixin, FormView):
    """Second-factor challenge for a session that has only a password."""

    template_name = "household/otp_verify.html"
    form_class = OTPTokenForm
    page_title = "Two-factor"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.is_verified():
            return redirect("household:today")

        return super().dispatch(request, *args, **kwargs)

    def get_device(self):
        return TOTPDevice.objects.filter(
            user=self.request.user, confirmed=True
        ).first()

    def dispatch_no_device(self):
        return redirect("household:otp_setup")

    def form_valid(self, form):
        device = self.get_device()

        if device is None:
            return self.dispatch_no_device()

        # django-otp throttles repeated failures with an increasing delay,
        # which is what keeps a six-digit code from being brute-forceable.
        allowed, _ = device.verify_is_allowed()

        if not allowed:
            form.add_error(
                None,
                "Too many incorrect codes. Wait a moment before trying again.",
            )
            return self.form_invalid(form)

        if not device.verify_token(form.cleaned_data["token"]):
            form.add_error("token", "That code didn't match. Try the current one.")
            return self.form_invalid(form)

        otp_login(self.request, device)

        return redirect(self.get_success_url())

    def get_success_url(self):
        # Shared validator rather than an inline check, so every place that
        # honours a caller-supplied destination rejects the same things.
        return safe_next(self.request, default=reverse("household:today"))
