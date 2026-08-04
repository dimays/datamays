"""The header nav and account dropdown: what lives where."""

from django.test import TestCase
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from .test_access import make_user


class HeaderNavTests(TestCase):
    def setUp(self):
        self.user = make_user("david", with_device=True)
        self.client.force_login(self.user)
        session = self.client.session
        session["otp_device_id"] = TOTPDevice.objects.get(user=self.user).persistent_id
        session.save()

    def test_settings_help_and_import_are_top_level_nav_links(self):
        response = self.client.get(reverse("finance:home"))
        body = response.content.decode()
        settings_href = reverse("finance:settings")
        help_href = reverse("finance:help")
        imports_href = reverse("finance:imports")

        for href in [settings_href, help_href, imports_href]:
            self.assertIn(f'href="{href}"', body)

    def test_the_dropdown_only_has_user_specific_items(self):
        response = self.client.get(reverse("finance:home"))
        body = response.content.decode()

        dropdown_start = body.index('role="menu"')
        dropdown = body[dropdown_start:]

        self.assertIn("Alerts", dropdown)
        self.assertIn("Preferences", dropdown)
        self.assertIn("Back to datamays.com", dropdown)
        self.assertIn("Sign out", dropdown)
        self.assertNotIn(">Settings<", dropdown)
        self.assertNotIn(">Help<", dropdown)

    def test_settings_nav_item_is_active_on_a_settings_subpage(self):
        response = self.client.get(reverse("finance:rules"))

        secondary = response.context["secondary_nav_items"]
        settings_item = next(item for item in secondary if item["url_name"] == "settings")

        self.assertTrue(settings_item["is_active"])

    def test_import_data_link_points_at_the_imports_page(self):
        response = self.client.get(reverse("finance:home"))
        body = response.content.decode()

        self.assertIn("Import data", body)
        self.assertIn(f'href="{reverse("finance:imports")}"', body)
