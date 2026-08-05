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

    def test_settings_and_import_are_top_level_nav_links(self):
        response = self.client.get(reverse("finance:home"))
        body = response.content.decode()
        settings_href = reverse("finance:settings")
        imports_href = reverse("finance:imports")

        for href in [settings_href, imports_href]:
            self.assertIn(f'href="{href}"', body)

    def test_help_is_not_a_top_level_nav_link(self):
        response = self.client.get(reverse("finance:home"))

        secondary = response.context["secondary_nav_items"]
        self.assertNotIn("help", [item["url_name"] for item in secondary])

    def test_the_dropdown_has_help_and_user_specific_items(self):
        response = self.client.get(reverse("finance:home"))
        body = response.content.decode()

        # Bounded to the header: the dropdown lives entirely inside it, and
        # both the primary/secondary nav and the mobile tab bar (which also
        # legitimately says "Settings") live outside it.
        dropdown_start = body.index('role="menu"')
        dropdown_end = body.index("</header>", dropdown_start)
        dropdown = body[dropdown_start:dropdown_end]

        self.assertIn("Alerts", dropdown)
        self.assertIn("Preferences", dropdown)
        self.assertIn(">Help<", dropdown)
        self.assertIn("Back to datamays.com", dropdown)
        self.assertIn("Sign out", dropdown)
        self.assertNotIn(">Settings<", dropdown)

    def test_settings_nav_item_is_active_on_a_settings_subpage(self):
        response = self.client.get(reverse("finance:rules"))

        secondary = response.context["secondary_nav_items"]
        settings_item = next(item for item in secondary if item["url_name"] == "settings")

        self.assertTrue(settings_item["is_active"])

    def test_import_data_link_points_at_the_imports_page(self):
        response = self.client.get(reverse("finance:home"))
        body = response.content.decode()

        self.assertIn("Import", body)
        self.assertIn(f'href="{reverse("finance:imports")}"', body)

    def test_settings_comes_after_import_in_the_desktop_nav(self):
        response = self.client.get(reverse("finance:home"))

        secondary = response.context["secondary_nav_items"]
        self.assertEqual(
            [item["url_name"] for item in secondary], ["imports", "settings"]
        )

    def test_the_mobile_tab_bar_matches_the_desktop_nav(self):
        # The bug report this guards against: the footer tab bar only ever
        # rendered PRIMARY_NAV, so Settings/Import were reachable on desktop
        # but invisible on a phone.
        response = self.client.get(reverse("finance:home"))
        body = response.content.decode()

        tab_bar_start = body.index('aria-label="Primary"')
        tab_bar = body[tab_bar_start:]

        for href in [reverse("finance:settings"), reverse("finance:imports")]:
            self.assertIn(f'href="{href}"', tab_bar)

    def test_settings_comes_after_import_in_the_mobile_tab_bar(self):
        response = self.client.get(reverse("finance:home"))
        body = response.content.decode()

        tab_bar_start = body.index('aria-label="Primary"')
        tab_bar = body[tab_bar_start:]

        imports_index = tab_bar.index(f'href="{reverse("finance:imports")}"')
        settings_index = tab_bar.index(f'href="{reverse("finance:settings")}"')
        self.assertLess(imports_index, settings_index)

    def test_import_does_not_get_a_call_to_action_treatment(self):
        # Explicitly dropped: it looked out of place next to the plain
        # icon/text nav items everywhere else.
        response = self.client.get(reverse("finance:home"))
        body = response.content.decode()

        tab_bar_start = body.index('aria-label="Primary"')
        imports_index = body.index(f'href="{reverse("finance:imports")}"', tab_bar_start)

        self.assertNotIn("bg-primary", body[imports_index:imports_index + 400])

    def test_no_stray_template_comment_leaks_into_the_page(self):
        # Regression: a {# #} comment spanning multiple lines is not stripped
        # by Django and was rendering as literal text on every page.
        response = self.client.get(reverse("finance:qfrs"))

        self.assertNotContains(response, "Thumb-reachable")
