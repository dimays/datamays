"""Finance's routes sit behind the household gate.

The sign-in flow itself belongs to the household shell and is tested in
`household/tests/test_access.py`. `make_user` is re-exported here because
most of finance's test files import it from this module.
"""

from django.test import TestCase
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from household.tests.factories import PASSWORD, make_member as make_user  # noqa: F401

PROTECTED_URL_NAMES = [
    "home",
    "transactions",
    "charts",
    "settings",
    "preferences",
]


class AnonymousAccessTests(TestCase):
    def test_every_protected_route_returns_403(self):
        for name in PROTECTED_URL_NAMES:
            with self.subTest(route=name):
                response = self.client.get(reverse(f"finance:{name}"))
                self.assertEqual(response.status_code, 403)

    def test_403_does_not_redirect_to_login(self):
        # A redirect would confirm to a stranger that credentials exist here.
        response = self.client.get(reverse("finance:home"))
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "household/403.html")

    def test_403_page_is_cheeky_and_leaks_no_financial_terms(self):
        response = self.client.get(reverse("finance:home"))
        body = response.content.decode()

        self.assertIn("Get out of here, nosey!", body)
        for term in ["balance", "budget", "transaction", "account"]:
            self.assertNotIn(term, body.lower())

class NonMemberAccessTests(TestCase):
    def test_authenticated_outsider_is_indistinguishable_from_a_stranger(self):
        self.client.force_login(make_user("outsider", in_group=False))

        response = self.client.get(reverse("finance:home"))

        # Same 403, same page: a valid site login must not reveal that the
        # finance app exists behind a group check.
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "household/403.html")


class SecondFactorTests(TestCase):
    def test_member_without_a_device_is_sent_to_enrollment(self):
        self.client.force_login(make_user("david"))

        response = self.client.get(reverse("finance:home"))

        self.assertRedirects(response, reverse("household:otp_setup"))

    def test_member_with_a_device_is_challenged_before_seeing_data(self):
        self.client.force_login(make_user("maddie", with_device=True))

        response = self.client.get(reverse("finance:home"))

        self.assertRedirects(response, reverse("household:otp_verify") + "?next=%2Ffinance%2F")

    def test_password_alone_never_reaches_a_finance_page(self):
        self.client.force_login(make_user("maddie", with_device=True))

        for name in PROTECTED_URL_NAMES:
            with self.subTest(route=name):
                response = self.client.get(reverse(f"finance:{name}"))
                self.assertEqual(response.status_code, 302)

    def test_verified_session_reaches_the_app(self):
        user = make_user("david", with_device=True)
        self.client.force_login(user)

        # Mirror what OTPSetupView/OTPVerifyView do on a correct code.
        device = TOTPDevice.objects.get(user=user)
        session = self.client.session
        session["otp_device_id"] = device.persistent_id
        session.save()

        response = self.client.get(reverse("finance:home"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "finance/home.html")
