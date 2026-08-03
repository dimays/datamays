from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

FINANCE_URL_NAMES = [
    "home",
    "transactions",
    "spend",
    "income",
    "savings",
    "settings",
    "preferences",
]


class FinanceAccessTests(TestCase):
    def test_every_finance_route_is_closed_to_anonymous_visitors(self):
        for name in FINANCE_URL_NAMES:
            with self.subTest(route=name):
                response = self.client.get(reverse(f"finance:{name}"))
                self.assertEqual(response.status_code, 403)

    def test_anonymous_response_leaks_nothing_about_the_app(self):
        response = self.client.get(reverse("finance:home"))
        body = response.content.decode().lower()
        for term in ["balance", "budget", "transaction", "account"]:
            self.assertNotIn(term, body)

    def test_authenticated_user_reaches_the_app(self):
        User.objects.create_user(username="maddie", password="correct-horse-battery")
        self.client.login(username="maddie", password="correct-horse-battery")

        response = self.client.get(reverse("finance:home"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "finance/home.html")
