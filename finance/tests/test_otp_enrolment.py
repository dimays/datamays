"""Full second-factor enrolment and challenge, using real TOTP codes."""

import time

from django.test import TestCase
from django.urls import reverse
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice

from .test_access import make_user


def current_token(device: TOTPDevice) -> str:
    """The code an authenticator app would be showing right now."""
    totp = TOTP(device.bin_key, device.step, device.t0, device.digits)
    totp.time = time.time()

    return f"{totp.token():0{device.digits}d}"


class EnrolmentTests(TestCase):
    def setUp(self):
        self.user = make_user("david")
        self.client.force_login(self.user)

    def test_setup_page_offers_a_scannable_secret(self):
        response = self.client.get(reverse("finance:otp_setup"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<svg")

        device = TOTPDevice.objects.get(user=self.user, confirmed=False)
        self.assertContains(response, device.key)

    def test_reloading_setup_keeps_the_same_secret(self):
        # Otherwise a user who scans, then refreshes, holds a dead secret.
        self.client.get(reverse("finance:otp_setup"))
        first = TOTPDevice.objects.get(user=self.user, confirmed=False).key

        self.client.get(reverse("finance:otp_setup"))
        second = TOTPDevice.objects.get(user=self.user, confirmed=False).key

        self.assertEqual(first, second)

    def test_a_correct_code_confirms_the_device_and_opens_the_app(self):
        self.client.get(reverse("finance:otp_setup"))
        device = TOTPDevice.objects.get(user=self.user, confirmed=False)

        response = self.client.post(
            reverse("finance:otp_setup"), {"token": current_token(device)}
        )

        self.assertRedirects(response, reverse("finance:home"))

        device.refresh_from_db()
        self.assertTrue(device.confirmed)

        # And the session is now verified, so the app is actually reachable.
        self.assertEqual(self.client.get(reverse("finance:home")).status_code, 200)

    def test_a_wrong_code_leaves_the_device_unconfirmed(self):
        self.client.get(reverse("finance:otp_setup"))

        response = self.client.post(reverse("finance:otp_setup"), {"token": "000000"})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            TOTPDevice.objects.filter(user=self.user, confirmed=True).exists()
        )
        self.assertEqual(self.client.get(reverse("finance:home")).status_code, 302)


class ChallengeTests(TestCase):
    def setUp(self):
        self.user = make_user("maddie")
        self.device = TOTPDevice.objects.create(
            user=self.user, name="test", confirmed=True
        )
        self.client.force_login(self.user)

    def test_correct_code_verifies_the_session(self):
        response = self.client.post(
            reverse("finance:otp_verify"), {"token": current_token(self.device)}
        )

        self.assertRedirects(response, reverse("finance:home"))
        self.assertEqual(self.client.get(reverse("finance:home")).status_code, 200)

    def test_wrong_code_leaves_the_session_unverified(self):
        response = self.client.post(reverse("finance:otp_verify"), {"token": "000000"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(reverse("finance:home")).status_code, 302)

    def test_a_code_cannot_be_replayed(self):
        token = current_token(self.device)

        self.client.post(reverse("finance:otp_verify"), {"token": token})
        self.client.post(reverse("finance:logout"))
        self.client.force_login(self.user)

        response = self.client.post(reverse("finance:otp_verify"), {"token": token})

        # django-otp records the last used counter, so a captured code is dead.
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(reverse("finance:home")).status_code, 302)

    def test_already_verified_users_skip_the_challenge(self):
        self.client.post(
            reverse("finance:otp_verify"), {"token": current_token(self.device)}
        )

        response = self.client.get(reverse("finance:otp_verify"))

        self.assertRedirects(response, reverse("finance:home"))
