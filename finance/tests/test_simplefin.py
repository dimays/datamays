"""SimpleFIN adapter, against mocked HTTP only.

Nothing here reaches a real institution or a real SimpleFIN bridge.
"""

import base64
from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from finance.providers.base import ProviderAuthError, ProviderError
from finance.providers.simplefin import SimpleFINAdapter, claim_access_url

ACCESS_URL = "https://user:secret@bridge.simplefin.org/simplefin"


def response(*, status=200, json_data=None, text=""):
    mock = Mock()
    mock.status_code = status
    mock.ok = 200 <= status < 300
    mock.text = text
    mock.json.return_value = json_data if json_data is not None else {}
    return mock


ACCOUNTS_PAYLOAD = {
    "errors": [],
    "accounts": [
        {
            "id": "ACT-checking-1",
            "name": "Joint Checking",
            "currency": "USD",
            "balance": "4210.55",
            "available-balance": "4100.55",
            "balance-date": 1775000000,
            "org": {"name": "Byline Bank", "domain": "bylinebank.com"},
            "transactions": [
                {
                    "id": "TXN-1",
                    "posted": 1774915200,
                    "amount": "-42.50",
                    "description": "MARIANOS #1234 CHICAGO IL",
                    "payee": "Marianos",
                },
                {
                    "id": "TXN-2",
                    "posted": 1774915200,
                    "amount": "2500.00",
                    "description": "ACME PAYROLL DIRECT DEP",
                    "pending": False,
                },
            ],
        }
    ],
}


class ClaimAccessUrlTests(SimpleTestCase):
    def token_for(self, url):
        return base64.b64encode(url.encode()).decode()

    @patch("finance.providers.simplefin.requests.post")
    def test_a_valid_token_returns_the_access_url(self, post):
        post.return_value = response(text=ACCESS_URL)

        self.assertEqual(
            claim_access_url(self.token_for("https://bridge.simplefin.org/claim/abc")),
            ACCESS_URL,
        )

    def test_an_empty_token_is_rejected_before_any_request(self):
        with self.assertRaises(ProviderError):
            claim_access_url("   ")

    def test_a_malformed_token_gives_actionable_guidance(self):
        with self.assertRaises(ProviderError) as caught:
            claim_access_url("this is not base64!!")

        self.assertIn("setup token", str(caught.exception))

    def test_a_token_decoding_to_plain_http_is_refused(self):
        # Claiming over HTTP would put the credential on the wire in clear text.
        with self.assertRaises(ProviderError):
            claim_access_url(self.token_for("http://bridge.simplefin.org/claim/abc"))

    @patch("finance.providers.simplefin.requests.post")
    def test_a_reused_token_reports_that_it_must_be_regenerated(self, post):
        post.return_value = response(status=403)

        with self.assertRaises(ProviderAuthError) as caught:
            claim_access_url(self.token_for("https://bridge.simplefin.org/claim/abc"))

        self.assertIn("once", str(caught.exception))


class FetchTests(SimpleTestCase):
    def setUp(self):
        self.adapter = SimpleFINAdapter()

    @patch("finance.providers.simplefin.requests.get")
    def test_accounts_and_transactions_are_normalized(self, get):
        get.return_value = response(json_data=ACCOUNTS_PAYLOAD)

        result = self.adapter.fetch(access_secret=ACCESS_URL, since=date(2026, 1, 1))

        self.assertEqual(len(result.accounts), 1)

        account = result.accounts[0]
        self.assertEqual(account.provider_account_id, "ACT-checking-1")
        self.assertEqual(account.raw_balance, Decimal("4210.55"))
        self.assertEqual(account.institution_name, "Byline Bank")

        transactions = result.transactions["ACT-checking-1"]
        self.assertEqual(len(transactions), 2)
        self.assertEqual(transactions[0].amount, Decimal("-42.50"))
        self.assertEqual(transactions[0].merchant, "Marianos")

    @patch("finance.providers.simplefin.requests.get")
    def test_amounts_are_decimal_not_float(self, get):
        get.return_value = response(json_data=ACCOUNTS_PAYLOAD)

        result = self.adapter.fetch(access_secret=ACCESS_URL, since=date(2026, 1, 1))

        for transaction in result.transactions["ACT-checking-1"]:
            self.assertIsInstance(transaction.amount, Decimal)

    @patch("finance.providers.simplefin.requests.get")
    def test_the_since_date_is_sent_as_an_epoch_start_date(self, get):
        get.return_value = response(json_data=ACCOUNTS_PAYLOAD)

        self.adapter.fetch(access_secret=ACCESS_URL, since=date(2026, 4, 1))

        # 2026-04-01T00:00:00Z — midnight UTC on the requested day, so the
        # window never silently clips the first day's transactions.
        self.assertEqual(get.call_args.kwargs["params"]["start-date"], 1775001600)

    @patch("finance.providers.simplefin.requests.get")
    def test_provider_errors_are_carried_through_rather_than_raised(self, get):
        # One institution failing to refresh must not discard the others.
        get.return_value = response(
            json_data={"errors": ["Connection to Chase failed."], "accounts": []}
        )

        result = self.adapter.fetch(access_secret=ACCESS_URL, since=date(2026, 1, 1))

        self.assertEqual(result.errors, ["Connection to Chase failed."])

    @patch("finance.providers.simplefin.requests.get")
    def test_rejected_credentials_raise_an_auth_error(self, get):
        get.return_value = response(status=403)

        with self.assertRaises(ProviderAuthError):
            self.adapter.fetch(access_secret=ACCESS_URL, since=date(2026, 1, 1))

    @patch("finance.providers.simplefin.requests.get")
    def test_non_json_response_is_reported_clearly(self, get):
        broken = response()
        broken.json.side_effect = ValueError("not json")
        get.return_value = broken

        with self.assertRaises(ProviderError):
            self.adapter.fetch(access_secret=ACCESS_URL, since=date(2026, 1, 1))

    @patch("finance.providers.simplefin.requests.get")
    def test_rows_missing_a_date_amount_or_id_are_dropped_not_invented(self, get):
        get.return_value = response(
            json_data={
                "accounts": [
                    {
                        "id": "ACT-1",
                        "name": "Checking",
                        "balance": "10.00",
                        "transactions": [
                            {"id": "GOOD", "posted": 1774915200, "amount": "-1.00", "description": "ok"},
                            {"id": "NO-DATE", "amount": "-1.00", "description": "missing date"},
                            {"id": "NO-AMOUNT", "posted": 1774915200, "description": "missing amount"},
                            {"posted": 1774915200, "amount": "-1.00", "description": "missing id"},
                        ],
                    }
                ]
            }
        )

        result = self.adapter.fetch(access_secret=ACCESS_URL, since=date(2026, 1, 1))

        kept = result.transactions["ACT-1"]
        self.assertEqual([t.provider_txn_id for t in kept], ["GOOD"])

    @patch("finance.providers.simplefin.requests.get")
    def test_an_unparseable_balance_is_reported_rather_than_guessed(self, get):
        get.return_value = response(
            json_data={"accounts": [{"id": "ACT-1", "name": "X", "balance": "four dollars"}]}
        )

        with self.assertRaises(ProviderError):
            self.adapter.fetch(access_secret=ACCESS_URL, since=date(2026, 1, 1))

    @patch("finance.providers.simplefin.requests.get")
    def test_a_network_failure_is_wrapped_not_leaked(self, get):
        import requests

        get.side_effect = requests.ConnectionError("no route to host")

        with self.assertRaises(ProviderError):
            self.adapter.fetch(access_secret=ACCESS_URL, since=date(2026, 1, 1))
