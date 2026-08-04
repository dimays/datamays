"""The in-app help page: gated like everything else, and actually renders."""

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from .test_access import make_user


class HelpPageTests(TestCase):
    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)

    def test_the_page_is_gated_like_everything_else(self):
        response = self.client.get(reverse("finance:help"))
        self.assertEqual(response.status_code, 403)

    def test_a_signed_in_user_sees_every_screen_covered(self):
        user = make_user("david", with_device=True)
        self.client.force_login(user)
        session = self.client.session
        session["otp_device_id"] = TOTPDevice.objects.get(user=user).persistent_id
        session.save()

        response = self.client.get(reverse("finance:help"))

        self.assertEqual(response.status_code, 200)
        for heading in ["Home", "Activity", "Budgets", "Settings", "Imports", "QFRs", "Preferences"]:
            with self.subTest(heading=heading):
                self.assertContains(response, heading)

    def test_the_header_menu_links_to_it(self):
        user = make_user("david", with_device=True)
        self.client.force_login(user)
        session = self.client.session
        session["otp_device_id"] = TOTPDevice.objects.get(user=user).persistent_id
        session.save()

        response = self.client.get(reverse("finance:home"))

        self.assertContains(response, reverse("finance:help"))
