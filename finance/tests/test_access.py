from django.conf import settings
from django.contrib.auth.models import Group, User
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from finance.access import FINANCE_GROUP
from finance.redirects import is_safe_path, safe_next
from finance.views.auth import OTPVerifyView

PROTECTED_URL_NAMES = [
    "home",
    "transactions",
    "charts",
    "settings",
    "preferences",
]

PASSWORD = "a-long-enough-test-password"


def make_user(username, *, in_group=True, with_device=False):
    user = User.objects.create_user(username=username, password=PASSWORD)

    if in_group:
        group, _ = Group.objects.get_or_create(name=FINANCE_GROUP)
        user.groups.add(group)

    if with_device:
        TOTPDevice.objects.create(user=user, name="test", confirmed=True)

    return user


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
        self.assertTemplateUsed(response, "finance/403.html")

    def test_403_page_is_cheeky_and_leaks_no_financial_terms(self):
        response = self.client.get(reverse("finance:home"))
        body = response.content.decode()

        self.assertIn("Get out of here, nosey!", body)
        for term in ["balance", "budget", "transaction", "account"]:
            self.assertNotIn(term, body.lower())

    def test_login_page_is_reachable(self):
        response = self.client.get(reverse("finance:login"))
        self.assertEqual(response.status_code, 200)


class NonMemberAccessTests(TestCase):
    def test_authenticated_outsider_is_indistinguishable_from_a_stranger(self):
        self.client.force_login(make_user("outsider", in_group=False))

        response = self.client.get(reverse("finance:home"))

        # Same 403, same page: a valid site login must not reveal that the
        # finance app exists behind a group check.
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "finance/403.html")


class SecondFactorTests(TestCase):
    def test_member_without_a_device_is_sent_to_enrolment(self):
        self.client.force_login(make_user("david"))

        response = self.client.get(reverse("finance:home"))

        self.assertRedirects(response, reverse("finance:otp_setup"))

    def test_member_with_a_device_is_challenged_before_seeing_data(self):
        self.client.force_login(make_user("maddie", with_device=True))

        response = self.client.get(reverse("finance:home"))

        self.assertRedirects(response, reverse("finance:otp_verify"))

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


class LoginFlowTests(TestCase):
    """Exercises the real form POST, which is what Axes instruments."""

    def test_correct_credentials_land_on_the_second_factor(self):
        make_user("david")

        response = self.client.post(
            reverse("finance:login"),
            {"username": "david", "password": PASSWORD},
        )

        # Signed in, but the session is not verified until TOTP is cleared.
        self.assertRedirects(
            response, reverse("finance:home"), target_status_code=302
        )

    def test_wrong_password_does_not_authenticate(self):
        make_user("david")

        response = self.client.post(
            reverse("finance:login"),
            {"username": "david", "password": "not-the-password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_repeated_failures_lock_the_account_out(self):
        make_user("david")

        for _ in range(settings.AXES_FAILURE_LIMIT):
            self.client.post(
                reverse("finance:login"),
                {"username": "david", "password": "wrong"},
            )

        # Even the correct password is refused once the lockout engages.
        response = self.client.post(
            reverse("finance:login"),
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
        view.request = self.factory.get(reverse("finance:otp_verify"), {"next": next_value})
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
                self.assertEqual(self._success_url_for(value), reverse("finance:home"))

    def test_relative_next_is_honoured(self):
        self.assertEqual(self._success_url_for("/finance/spend/"), "/finance/spend/")


class RedirectSafetyTests(SimpleTestCase):
    """`next` is attacker-controllable wherever it is honoured."""

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
