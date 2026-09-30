"""The shared sign-in: the gate, the login flow, lockout, and redirect safety.

Finance's own routes are proven gated in `finance/tests/test_access.py`;
`EveryRouteIsGatedTests` below walks every private URL in both apps, so a new
view that forgets the gate fails here without anyone adding it to a list.
"""

from django.conf import settings
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from household.redirects import is_safe_path, safe_next
from household.views.auth import OTPVerifyView

from .factories import PASSWORD, make_member as make_user

PRIVATE_NAMESPACES = {"household", "finance"}

# Reachable by anyone, because they are how you get in (or out). Everything
# else in a private namespace must refuse a stranger.
PUBLIC_ROUTES = {"household:login", "household:logout"}


def private_routes():
    """Every named route in the private apps, as a reversible URL.

    Walks the real resolver rather than a hand-kept list, so a view added
    tomorrow is covered today. Path converters get a placeholder of 1 — the
    gate runs in dispatch, before any lookup could 404.
    """
    routes = []

    def walk(patterns, namespace):
        for entry in patterns:
            if isinstance(entry, URLResolver):
                walk(entry.url_patterns, entry.namespace or namespace)
            elif isinstance(entry, URLPattern) and entry.name and namespace in PRIVATE_NAMESPACES:
                name = f"{namespace}:{entry.name}"
                kwargs = {key: 1 for key in entry.pattern.converters}
                routes.append((name, reverse(name, kwargs=kwargs or None)))

    walk(get_resolver().url_patterns, None)
    return routes


class EveryRouteIsGatedTests(TestCase):
    def test_the_walk_finds_both_apps(self):
        names = {name for name, _ in private_routes()}

        self.assertIn("household:today", names)
        self.assertIn("finance:home", names)
        self.assertGreater(len(names), 40)

    def test_a_stranger_gets_403_everywhere(self):
        for name, url in private_routes():
            if name in PUBLIC_ROUTES:
                continue
            with self.subTest(route=name):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_a_signed_in_outsider_gets_403_everywhere(self):
        self.client.force_login(make_user("outsider", in_group=False))

        for name, url in private_routes():
            if name in PUBLIC_ROUTES:
                continue
            with self.subTest(route=name):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_the_403_is_the_same_page_from_either_app(self):
        for url in (reverse("household:today"), reverse("finance:home")):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 403)
                self.assertTemplateUsed(response, "household/403.html")


class OldSignInURLTests(TestCase):
    """Sign-in moved from /finance to /household; bookmarks must still work."""

    def test_old_paths_redirect_and_keep_next(self):
        for old, new in [
            ("/finance/login/", "household:login"),
            ("/finance/two-factor/", "household:otp_verify"),
            ("/finance/two-factor/setup/", "household:otp_setup"),
        ]:
            with self.subTest(old=old):
                response = self.client.get(old + "?next=/finance/charts/")
                self.assertRedirects(
                    response,
                    reverse(new) + "?next=/finance/charts/",
                    fetch_redirect_response=False,
                )

    def test_the_requested_page_survives_the_second_factor(self):
        """A bookmark to /finance/charts/ should land on Charts, not on Today."""
        from django_otp.plugins.otp_totp.models import TOTPDevice

        from .test_otp_enrollment import current_token

        user = make_user("maddie", with_device=True)
        self.client.force_login(user)

        challenge = self.client.get(reverse("finance:charts"))
        self.assertRedirects(
            challenge,
            reverse("household:otp_verify") + "?next=%2Ffinance%2Fcharts%2F",
            fetch_redirect_response=False,
        )

        response = self.client.post(
            challenge["Location"], {"token": current_token(TOTPDevice.objects.get(user=user))}
        )

        self.assertRedirects(response, reverse("finance:charts"))

    def test_a_password_sign_in_is_sent_on_to_the_second_factor(self):
        make_user("david", with_device=True)

        response = self.client.post(
            reverse("household:login"), {"username": "david", "password": PASSWORD}, follow=True
        )

        self.assertTemplateUsed(response, "household/otp_verify.html")


class LoginFlowTests(TestCase):
    """Exercises the real form POST, which is what Axes instruments."""

    def test_correct_credentials_land_on_the_second_factor(self):
        make_user("david")

        response = self.client.post(
            reverse("household:login"),
            {"username": "david", "password": PASSWORD},
        )

        # Signed in, but the session is not verified until TOTP is cleared.
        self.assertRedirects(
            response, reverse("household:today"), target_status_code=302
        )

    def test_wrong_password_does_not_authenticate(self):
        make_user("david")

        response = self.client.post(
            reverse("household:login"),
            {"username": "david", "password": "not-the-password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_repeated_failures_lock_the_account_out(self):
        make_user("david")

        for _ in range(settings.AXES_FAILURE_LIMIT):
            self.client.post(
                reverse("household:login"),
                {"username": "david", "password": "wrong"},
            )

        # Even the correct password is refused once the lockout engages.
        response = self.client.post(
            reverse("household:login"),
            {"username": "david", "password": PASSWORD},
        )

        self.assertEqual(response.status_code, 429)
        self.assertIn("Too many attempts", response.content.decode())
        self.assertFalse(response.wsgi_request.user.is_authenticated)


class OTPRedirectSafetyTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _success_url_for(self, next_value):
        view = OTPVerifyView()
        view.request = self.factory.get(reverse("household:otp_verify"), {"next": next_value})
        return view.get_success_url()

    def test_next_parameter_cannot_bounce_to_another_host(self):
        hostile = [
            "//evil.example.com",
            "https://evil.example.com",
            "javascript:alert(1)",
            "\\\\evil.example.com",
        ]

        for value in hostile:
            with self.subTest(next=value):
                self.assertEqual(self._success_url_for(value), reverse("household:today"))

    def test_relative_next_is_honored(self):
        self.assertEqual(self._success_url_for("/finance/spend/"), "/finance/spend/")


class RedirectSafetyTests(SimpleTestCase):
    """`next` is attacker-controllable wherever it is honored."""

    def test_hostile_targets_are_rejected(self):
        hostile = [
            "//evil.example.com",
            "https://evil.example.com",
            "http://evil.example.com",
            "javascript:alert(1)",
            "\\\\evil.example.com",
            "/finance/\r\nSet-Cookie: x=1",
            "",
            None,
        ]

        for value in hostile:
            with self.subTest(next=value):
                self.assertFalse(is_safe_path(value))

    def test_same_site_paths_are_allowed(self):
        for value in ["/finance/", "/finance/transactions/?review=1"]:
            with self.subTest(next=value):
                self.assertTrue(is_safe_path(value))

    def test_safe_next_uses_the_caller_supplied_default_when_unsafe(self):
        request = RequestFactory().post("/finance/x/", {"next": "//evil.example.com"})

        self.assertEqual(safe_next(request, default="/finance/"), "/finance/")

    def test_safe_next_honours_a_relative_target(self):
        request = RequestFactory().post("/finance/x/", {"next": "/finance/spend/"})

        self.assertEqual(safe_next(request, default="/finance/"), "/finance/spend/")
