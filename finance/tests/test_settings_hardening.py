"""Tests for the project-level security fixes that shipped with the auth gate."""

from django.test import SimpleTestCase

from datamays.settings import _scrub_finance_data


def event_with(url, *, frame_vars=None):
    return {
        "request": {"url": url, "data": {"password": "hunter2"}},
        "user": {"id": 1, "username": "david"},
        "exception": {
            "values": [
                {"stacktrace": {"frames": [{"vars": frame_vars or {"balance": "8412.19"}}]}}
            ]
        },
    }


class SentryScrubbingTests(SimpleTestCase):
    def test_finance_events_lose_request_user_and_frame_locals(self):
        event = _scrub_finance_data(event_with("https://datamays.com/finance/spend/"), {})

        self.assertNotIn("request", event)
        self.assertNotIn("user", event)

        frame = event["exception"]["values"][0]["stacktrace"]["frames"][0]
        self.assertNotIn("vars", frame)

    def test_no_balance_survives_anywhere_in_a_finance_event(self):
        event = _scrub_finance_data(
            event_with(
                "https://datamays.com/finance/",
                frame_vars={"current_balance": "8412.19", "account": "…4471"},
            ),
            {},
        )

        self.assertNotIn("8412.19", str(event))
        self.assertNotIn("4471", str(event))

    def test_public_site_events_are_left_intact(self):
        # send_default_pii is deliberately on for the portfolio site; the
        # scrubber must not quietly degrade that reporting.
        event = _scrub_finance_data(event_with("https://datamays.com/contact/"), {})

        self.assertIn("request", event)
        self.assertIn("user", event)
        self.assertIn(
            "vars", event["exception"]["values"][0]["stacktrace"]["frames"][0]
        )

    def test_events_without_request_data_do_not_crash_the_scrubber(self):
        self.assertEqual(_scrub_finance_data({}, {}), {})
