"""The sync service: idempotency, sign normalisation, and failure isolation."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from finance.models import (
    Account,
    AccountBalanceSnapshot,
    AccountConnection,
    AccountType,
    ConnectionStatus,
    SyncStatus,
    Transaction,
)
from finance.providers.base import (
    AccountPayload,
    FetchResult,
    ProviderAuthError,
    ProviderError,
    TransactionPayload,
)
from finance.services.sync import (
    guess_account_type,
    normalise_balance,
    sync_connection,
)

from .factories import make_account, make_institution


def account_payload(**kwargs):
    kwargs.setdefault("provider_account_id", "ACT-1")
    kwargs.setdefault("name", "Joint Checking")
    kwargs.setdefault("raw_balance", Decimal("4210.55"))
    kwargs.setdefault("balance_as_of", date(2026, 4, 15))
    return AccountPayload(**kwargs)


def transaction_payload(**kwargs):
    kwargs.setdefault("provider_txn_id", "TXN-1")
    kwargs.setdefault("posted_on", date(2026, 4, 15))
    kwargs.setdefault("amount", Decimal("-42.50"))
    kwargs.setdefault("description", "MARIANOS #1234")
    return TransactionPayload(**kwargs)


def fetch_result(accounts=None, transactions=None, errors=None):
    accounts = accounts if accounts is not None else [account_payload()]
    return FetchResult(
        accounts=accounts,
        transactions=transactions if transactions is not None else {"ACT-1": [transaction_payload()]},
        errors=errors or [],
    )


class SyncTestCase(TestCase):
    def setUp(self):
        self.institution = make_institution()
        self.connection = AccountConnection.objects.create(
            institution=self.institution,
            label="Byline (joint)",
            access_secret="https://user:secret@bridge.simplefin.org/simplefin",
        )

    def run_sync(self, result=None, side_effect=None):
        with patch("finance.services.sync.get_adapter") as get_adapter:
            adapter = get_adapter.return_value

            if side_effect is not None:
                adapter.fetch.side_effect = side_effect
            else:
                adapter.fetch.return_value = result if result is not None else fetch_result()

            return sync_connection(self.connection)


class IdempotencyTests(SyncTestCase):
    def test_a_first_sync_creates_the_account_and_transaction(self):
        run = self.run_sync()

        self.assertEqual(run.status, SyncStatus.SUCCESS)
        self.assertEqual(run.accounts_synced, 1)
        self.assertEqual(run.transactions_created, 1)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_re_running_immediately_creates_nothing(self):
        self.run_sync()
        second = self.run_sync()

        self.assertEqual(second.transactions_created, 0)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(Account.objects.count(), 1)

    def test_running_three_times_still_yields_one_row(self):
        for _ in range(3):
            self.run_sync()

        self.assertEqual(Transaction.objects.count(), 1)

    def test_a_pending_transaction_that_settles_is_updated_not_duplicated(self):
        self.run_sync(
            fetch_result(
                transactions={
                    "ACT-1": [
                        transaction_payload(amount=Decimal("-40.00"), is_pending=True)
                    ]
                }
            )
        )

        run = self.run_sync(
            fetch_result(
                transactions={
                    "ACT-1": [
                        transaction_payload(
                            amount=Decimal("-42.50"),
                            posted_on=date(2026, 4, 17),
                            is_pending=False,
                        )
                    ]
                }
            )
        )

        self.assertEqual(run.transactions_updated, 1)
        self.assertEqual(Transaction.objects.count(), 1)

        settled = Transaction.objects.get()
        self.assertEqual(settled.amount, Decimal("-42.50"))
        self.assertEqual(settled.posted_on, date(2026, 4, 17))
        self.assertFalse(settled.is_pending)

    def test_two_identical_transactions_on_one_day_both_survive(self):
        run = self.run_sync(
            fetch_result(
                transactions={
                    "ACT-1": [
                        transaction_payload(
                            provider_txn_id="A", amount=Decimal("-4.75"), description="STARBUCKS"
                        ),
                        transaction_payload(
                            provider_txn_id="B", amount=Decimal("-4.75"), description="STARBUCKS"
                        ),
                    ]
                }
            )
        )

        self.assertEqual(run.transactions_created, 2)
        self.assertEqual(Transaction.objects.count(), 2)

    def test_an_overlapping_backfill_window_does_not_duplicate(self):
        self.run_sync()

        # The routine window re-reads the previous week, so the same rows come
        # back on every run by design.
        run = self.run_sync()

        self.assertEqual(run.transactions_created, 0)


class BalanceNormalisationTests(SyncTestCase):
    def test_an_asset_balance_passes_through(self):
        self.run_sync()

        account = Account.objects.get()
        self.assertEqual(account.current_balance, Decimal("4210.55"))

    def test_a_credit_card_debt_is_stored_negative(self):
        run = self.run_sync(
            fetch_result(
                accounts=[
                    account_payload(name="Chase Sapphire Card", raw_balance=Decimal("1350.00"))
                ],
                transactions={},
            )
        )

        self.assertEqual(run.status, SyncStatus.SUCCESS)

        card = Account.objects.get()
        self.assertEqual(card.account_type, AccountType.CREDIT_CARD)
        self.assertEqual(card.current_balance, Decimal("-1350.00"))
        # And still reads as a positive debt in the UI.
        self.assertEqual(card.display_balance, Decimal("1350.00"))

    def test_an_overpaid_card_stays_a_positive_balance(self):
        # Negation rather than -abs() is what makes this come out right.
        card = make_account(
            self.institution, name="Card", account_type=AccountType.CREDIT_CARD
        )

        self.assertEqual(normalise_balance(Decimal("-50.00"), card), Decimal("50.00"))

    def test_an_institution_that_reports_debt_negative_can_be_corrected(self):
        card = make_account(
            self.institution,
            name="Card",
            account_type=AccountType.CREDIT_CARD,
            debt_reported_positive=False,
        )

        self.assertEqual(normalise_balance(Decimal("-1350.00"), card), Decimal("-1350.00"))

    def test_a_missing_balance_leaves_the_stored_one_alone(self):
        self.run_sync()
        self.run_sync(
            fetch_result(accounts=[account_payload(raw_balance=None)], transactions={})
        )

        self.assertEqual(Account.objects.get().current_balance, Decimal("4210.55"))


class BalanceSnapshotTests(SyncTestCase):
    def test_a_snapshot_is_recorded_for_the_chart(self):
        self.run_sync()

        snapshot = AccountBalanceSnapshot.objects.get()
        self.assertEqual(snapshot.as_of, date(2026, 4, 15))
        self.assertEqual(snapshot.current, Decimal("4210.55"))

    def test_two_syncs_on_one_day_overwrite_rather_than_stack(self):
        self.run_sync()
        self.run_sync(
            fetch_result(
                accounts=[account_payload(raw_balance=Decimal("4000.00"))], transactions={}
            )
        )

        self.assertEqual(AccountBalanceSnapshot.objects.count(), 1)
        self.assertEqual(AccountBalanceSnapshot.objects.get().current, Decimal("4000.00"))


class AccountDiscoveryTests(SyncTestCase):
    def test_account_types_are_guessed_from_the_name(self):
        cases = [
            ("Joint Checking", AccountType.CHECKING),
            ("Rainy Day Savings", AccountType.SAVINGS),
            ("Chase Sapphire Card", AccountType.CREDIT_CARD),
            ("Nelnet Student Loan", AccountType.STUDENT_LOAN),
            ("Home Mortgage", AccountType.MORTGAGE),
            ("Fidelity Roth IRA", AccountType.RETIREMENT),
            ("Something Unusual", AccountType.OTHER),
        ]

        for name, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(guess_account_type(name), expected)

    def test_a_household_rename_survives_the_next_sync(self):
        self.run_sync()

        account = Account.objects.get()
        account.name = "Everyday Account"
        account.save()

        self.run_sync()

        self.assertEqual(Account.objects.get().name, "Everyday Account")

    def test_a_household_type_correction_survives_the_next_sync(self):
        self.run_sync(
            fetch_result(accounts=[account_payload(name="Something Unusual")], transactions={})
        )

        account = Account.objects.get()
        account.account_type = AccountType.MONEY_MARKET
        account.save()

        self.run_sync(
            fetch_result(accounts=[account_payload(name="Something Unusual")], transactions={})
        )

        self.assertEqual(Account.objects.get().account_type, AccountType.MONEY_MARKET)


class FailureHandlingTests(SyncTestCase):
    def test_rejected_credentials_flag_the_connection_for_reauth(self):
        run = self.run_sync(side_effect=ProviderAuthError("access url rejected"))

        self.connection.refresh_from_db()
        self.assertEqual(run.status, SyncStatus.FAILED)
        self.assertEqual(self.connection.status, ConnectionStatus.NEEDS_REAUTH)

    def test_a_transport_error_marks_the_connection_but_not_for_reauth(self):
        run = self.run_sync(side_effect=ProviderError("no route to host"))

        self.connection.refresh_from_db()
        self.assertEqual(run.status, SyncStatus.FAILED)
        self.assertEqual(self.connection.status, ConnectionStatus.ERROR)

    def test_provider_reported_errors_produce_a_partial_run(self):
        run = self.run_sync(fetch_result(errors=["Chase refresh failed."]))

        self.assertEqual(run.status, SyncStatus.PARTIAL)
        self.assertIn("Chase", run.error_message)
        # The healthy account still landed.
        self.assertEqual(Transaction.objects.count(), 1)

    def test_one_bad_account_does_not_discard_the_good_ones(self):
        result = fetch_result(
            accounts=[
                account_payload(provider_account_id="ACT-1", name="Good"),
                account_payload(provider_account_id="ACT-2", name="Bad"),
            ],
            transactions={
                "ACT-1": [transaction_payload()],
                # A date of None blows up on save; the run must survive it.
                "ACT-2": [transaction_payload(provider_txn_id="TXN-BAD", posted_on=None)],
            },
        )

        run = self.run_sync(result)

        self.assertEqual(run.status, SyncStatus.PARTIAL)
        self.assertEqual(run.accounts_synced, 1)
        self.assertTrue(Transaction.objects.filter(provider_txn_id="TXN-1").exists())

    def test_a_disabled_connection_is_not_contacted(self):
        self.connection.status = ConnectionStatus.DISABLED
        self.connection.save()

        run = self.run_sync()

        self.assertEqual(run.status, SyncStatus.FAILED)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_a_connection_with_no_credential_is_not_contacted(self):
        self.connection.access_secret = ""
        self.connection.save()

        run = self.run_sync()

        self.assertEqual(run.status, SyncStatus.FAILED)

    def test_a_successful_run_clears_a_previous_error(self):
        self.run_sync(side_effect=ProviderError("temporary blip"))
        self.run_sync()

        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, ConnectionStatus.ACTIVE)
        self.assertEqual(self.connection.last_error, "")
        self.assertIsNotNone(self.connection.last_synced_at)


class SyncRunObservabilityTests(SyncTestCase):
    def test_every_attempt_is_recorded_with_counts(self):
        self.run_sync()

        run = self.connection.sync_runs.get()
        self.assertIsNotNone(run.finished_at)
        self.assertIsNotNone(run.duration_seconds)
        self.assertEqual(run.transactions_created, 1)

    def test_failures_are_recorded_too(self):
        self.run_sync(side_effect=ProviderError("boom"))

        run = self.connection.sync_runs.get()
        self.assertEqual(run.status, SyncStatus.FAILED)
        self.assertIn("boom", run.error_message)

    def test_the_connection_timestamp_advances_on_success(self):
        before = timezone.now()
        self.run_sync()

        self.connection.refresh_from_db()
        self.assertGreaterEqual(self.connection.last_synced_at, before)
