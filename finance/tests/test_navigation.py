"""Finance's section nav and the account dropdown: what lives where.

Finance is one section of the household shell. The shell's header and
mobile tab bar list the sections (see household/tests/test_shell.py); finance's
own screens are one level down, in the section nav strip rendered on every
finance page at every width.
"""

from django.test import TestCase
from django.urls import reverse

from household.tests.factories import sign_in

from .test_access import make_user


def section_nav(body):
    start = body.index('aria-label="Finance"')
    return body[start:body.index("</nav>", start)]


class SectionNavTests(TestCase):
    def setUp(self):
        self.user = make_user("david", with_device=True)
        sign_in(self.client, self.user)

    def test_every_finance_screen_is_in_the_section_nav(self):
        nav = section_nav(self.client.get(reverse("finance:home")).content.decode())

        for name in ["home", "transactions", "charts", "qfrs", "imports", "settings"]:
            with self.subTest(screen=name):
                self.assertIn(f'href="{reverse(f"finance:{name}")}"', nav)

    def test_the_section_nav_is_on_every_finance_page(self):
        # The regression this guards against is the old one in a new shape:
        # the mobile tab bar once rendered only the primary items, so
        # Settings and Import were reachable on desktop but not on a phone.
        # There is now one strip for every width, on every page.
        for name in ["home", "transactions", "charts", "qfrs", "budgets", "rules"]:
            with self.subTest(page=name):
                body = self.client.get(reverse(f"finance:{name}")).content.decode()
                self.assertIn(f'href="{reverse("finance:settings")}"', section_nav(body))

    def test_help_is_not_in_the_section_nav(self):
        response = self.client.get(reverse("finance:home"))

        items = response.context["finance_nav_items"]
        self.assertNotIn("help", [item["url_name"] for item in items])

    def test_settings_is_active_on_a_settings_subpage(self):
        response = self.client.get(reverse("finance:rules"))

        items = response.context["finance_nav_items"]
        settings_item = next(item for item in items if item["url_name"] == "settings")

        self.assertTrue(settings_item["is_active"])

    def test_settings_comes_last(self):
        response = self.client.get(reverse("finance:home"))

        items = response.context["finance_nav_items"]
        self.assertEqual([item["url_name"] for item in items][-2:], ["imports", "settings"])

        nav = section_nav(response.content.decode())
        self.assertLess(
            nav.index(f'href="{reverse("finance:imports")}"'),
            nav.index(f'href="{reverse("finance:settings")}"'),
        )

    def test_import_does_not_get_a_call_to_action_treatment(self):
        # Explicitly dropped: it looked out of place next to the plain
        # nav items everywhere else.
        nav = section_nav(self.client.get(reverse("finance:home")).content.decode())
        imports_index = nav.index(f'href="{reverse("finance:imports")}"')

        self.assertNotIn("bg-primary", nav[imports_index:imports_index + 400])

    def test_the_dropdown_has_help_and_user_specific_items(self):
        body = self.client.get(reverse("finance:home")).content.decode()

        # Bounded to the header: the dropdown lives entirely inside it.
        dropdown_start = body.index('role="menu"')
        dropdown = body[dropdown_start:body.index("</header>", dropdown_start)]

        self.assertIn("Alerts", dropdown)
        self.assertIn("Preferences", dropdown)
        self.assertIn(">Help<", dropdown)
        self.assertIn("Back to datamays.com", dropdown)
        self.assertIn("Sign out", dropdown)
        self.assertNotIn(">Settings<", dropdown)

    def test_no_stray_template_comment_leaks_into_the_page(self):
        # Regression: a {# #} comment spanning multiple lines is not stripped
        # by Django and was rendering as literal text on every page.
        response = self.client.get(reverse("finance:qfrs"))

        self.assertNotContains(response, "Thumb-reachable")
        self.assertNotContains(response, "one level below")
