"""The sync service: idempotency, sign normalization, and failure isolation."""

from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from io import StringIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from finance.dates import household_today
from finance.models import (
    Account,
    AccountBalanceSnapshot,
    AccountConnection,
    AccountType,
    BalanceSource,
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
    INITIAL_HISTORY_DAYS,
    default_since,
    guess_account_type,
    normalize_balance,
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


class InitialHistoryWindowTests(SyncTestCase):
    """The window requested on a brand-new connection must stay under
    SimpleFIN's 90-day cap regardless of what time of day the sync runs.

    Two sources of slop stack in the same direction: the adapter sends
    `since` as midnight UTC (so the true elapsed span to "now" always has a
    fractional day added on top of the nominal day count), and
    household_today() can already be a day behind UTC late in the evening in
    America/Chicago. Both are exercised here via the worst case: just before
    midnight Chicago time, when UTC has already rolled over to the next day.
    """

    def test_the_initial_window_never_exceeds_the_90_day_cap(self):
        worst_case_now = datetime(
            2026, 8, 4, 23, 59, 59, tzinfo=ZoneInfo("America/Chicago")
        )

        with patch("finance.dates.timezone.now", return_value=worst_case_now):
            since = default_since(self.connection)

        # Mirrors providers.simplefin._get_accounts' own construction of the
        # start-date param, so this checks what SimpleFIN actually receives.
        start_date_epoch = datetime(
            since.year, since.month, since.day, tzinfo=dt_timezone.utc
        ).timestamp()

        elapsed_seconds = worst_case_now.timestamp() - start_date_epoch

        self.assertLessEqual(elapsed_seconds, 90 * 86400)

    def test_the_constant_leaves_a_real_margin_under_90(self):
        # Guards against someone bumping this back toward 90 without
        # re-checking the worst case above.
        self.assertLessEqual(INITIAL_HISTORY_DAYS, 88)


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


class BalanceNormalizationTests(SyncTestCase):
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
        # display_balance is signed the same as current_balance -- the sign
        # is rendered explicitly in templates, not hidden at this layer.
        self.assertEqual(card.display_balance, Decimal("-1350.00"))

    def test_an_overpaid_card_stays_a_positive_balance(self):
        # Negation rather than -abs() is what makes this come out right.
        card = make_account(
            self.institution, name="Card", account_type=AccountType.CREDIT_CARD
        )

        self.assertEqual(normalize_balance(Decimal("-50.00"), card), Decimal("50.00"))

    def test_an_institution_that_reports_debt_negative_can_be_corrected(self):
        card = make_account(
            self.institution,
            name="Card",
            account_type=AccountType.CREDIT_CARD,
            debt_reported_positive=False,
        )

        self.assertEqual(normalize_balance(Decimal("-1350.00"), card), Decimal("-1350.00"))

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
        self.assertEqual(snapshot.current, Decimal("4210.55"))

    def test_the_snapshot_is_dated_today_not_by_the_providers_own_timestamp(self):
        """The payload says this balance was read on 15 April. It is still
        what the account holds *today*, and dating the snapshot back would
        leave the newest snapshot older than Account.current_balance — the
        gap that let a manual entry outrank a later sync."""
        self.run_sync()

        snapshot = AccountBalanceSnapshot.objects.get()
        self.assertEqual(snapshot.as_of, household_today())
        self.assertNotEqual(snapshot.as_of, date(2026, 4, 15))

    def test_the_newest_snapshot_agrees_with_the_cached_balance(self):
        """The invariant the Charts tab and the homepage both depend on."""
        self.run_sync()

        account = Account.objects.get()
        newest = account.balance_snapshots.order_by("-as_of").first()
        self.assertEqual(newest.current, account.current_balance)

    def test_a_sync_overwrites_a_manual_reading_entered_the_same_day(self):
        """Documented behavior for a connected account: a manual balance is
        only as durable as the next sync. It has to hold for the snapshot
        too, or Charts keeps showing the manual figure after the sync."""
        self.run_sync()
        account = Account.objects.get()

        AccountBalanceSnapshot.objects.update_or_create(
            account=account,
            as_of=household_today(),
            defaults={"current": Decimal("999.00"), "source": BalanceSource.MANUAL},
        )

        self.run_sync(
            fetch_result(
                accounts=[account_payload(raw_balance=Decimal("4000.00"))],
                transactions={},
            )
        )

        newest = account.balance_snapshots.order_by("-as_of").first()
        self.assertEqual(newest.current, Decimal("4000.00"))
        self.assertEqual(newest.source, BalanceSource.PROVIDER)

    def test_two_syncs_on_one_day_overwrite_rather_than_stack(self):
        self.run_sync()
        self.run_sync(
            fetch_result(
                accounts=[account_payload(raw_balance=Decimal("4000.00"))], transactions={}
            )
        )

        self.assertEqual(AccountBalanceSnapshot.objects.count(), 1)
        self.assertEqual(AccountBalanceSnapshot.objects.get().current, Decimal("4000.00"))


class RefreshAccountBalancesCommandTests(TestCase):
    """The repair tool for when the cache and the history have drifted."""

    def setUp(self):
        self.institution = make_institution()
        self.account = make_account(self.institution, name="Rollover IRA")
        AccountBalanceSnapshot.objects.create(
            account=self.account,
            as_of=household_today(),
            current=Decimal("19090.65"),
            source=BalanceSource.CSV,
        )

    def run_command(self, *args):
        out = StringIO()
        call_command("refresh_account_balances", *args, stdout=out)
        return out.getvalue()

    def test_it_writes_nothing_without_apply(self):
        output = self.run_command()

        self.account.refresh_from_db()
        self.assertIsNone(self.account.current_balance)
        self.assertIn("Would update", output)
        self.assertIn("Dry run", output)

    def test_apply_repoints_the_cache_at_the_newest_snapshot(self):
        self.run_command("--apply")

        self.account.refresh_from_db()
        self.assertEqual(self.account.current_balance, Decimal("19090.65"))

    def test_an_account_already_in_step_is_left_alone(self):
        self.run_command("--apply")
        output = self.run_command()

        self.assertIn("Every cached balance is current", output)

    def test_only_empty_skips_an_account_that_already_has_a_figure(self):
        """The conservative mode: fill gaps, never override a value some
        other path deliberately set."""
        self.account.current_balance = Decimal("123.45")
        self.account.save(update_fields=["current_balance"])

        self.run_command("--only-empty", "--apply")

        self.account.refresh_from_db()
        self.assertEqual(self.account.current_balance, Decimal("123.45"))

    def test_account_limits_it_to_one(self):
        other = make_account(self.institution, name="Roth IRA")
        AccountBalanceSnapshot.objects.create(
            account=other,
            as_of=household_today(),
            current=Decimal("16600.88"),
            source=BalanceSource.CSV,
        )

        self.run_command("--account", str(self.account.pk), "--apply")

        self.account.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.account.current_balance, Decimal("19090.65"))
        self.assertIsNone(other.current_balance)

    def test_an_account_with_no_snapshots_is_ignored(self):
        make_account(self.institution, name="Brand New")

        self.run_command("--apply")

        self.assertIsNone(
            Account.objects.get(name="Brand New").current_balance
        )


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


class InstitutionResolutionTests(SyncTestCase):
    """A single SimpleFIN connection can span more than one real institution —
    SimpleFIN Bridge lets a person link several to one setup token, so trusting
    connection.institution for every account would silently mislabel all but
    the first one. Each account's institution comes from the provider's own
    report of it instead."""

    def test_an_account_is_attributed_to_the_institution_the_provider_reports(self):
        self.run_sync(
            fetch_result(accounts=[account_payload(institution_name="Chase")])
        )

        account = Account.objects.get()
        self.assertEqual(account.institution.name, "Chase")

    def test_two_accounts_from_different_institutions_land_on_different_institutions(self):
        result = fetch_result(
            accounts=[
                account_payload(provider_account_id="ACT-1", institution_name="Chase"),
                account_payload(provider_account_id="ACT-2", institution_name="Capital One"),
            ],
            transactions={},
        )

        run = self.run_sync(result)

        self.assertEqual(run.status, SyncStatus.SUCCESS)
        chase = Account.objects.get(provider_account_id="ACT-1")
        capital_one = Account.objects.get(provider_account_id="ACT-2")
        self.assertEqual(chase.institution.name, "Chase")
        self.assertEqual(capital_one.institution.name, "Capital One")
        self.assertNotEqual(chase.institution_id, capital_one.institution_id)

    def test_a_repeat_institution_name_reuses_the_same_institution_row(self):
        result = fetch_result(
            accounts=[
                account_payload(provider_account_id="ACT-1", institution_name="Chase"),
                account_payload(provider_account_id="ACT-2", institution_name="Chase"),
            ],
            transactions={},
        )

        self.run_sync(result)

        institutions = {a.institution_id for a in Account.objects.all()}
        self.assertEqual(len(institutions), 1)

    def test_a_connection_with_no_fallback_institution_still_works_when_the_provider_reports_one(self):
        self.connection.institution = None
        self.connection.save()

        run = self.run_sync(
            fetch_result(accounts=[account_payload(institution_name="Chase")])
        )

        self.assertEqual(run.status, SyncStatus.SUCCESS)
        self.assertEqual(Account.objects.get().institution.name, "Chase")

    def test_falls_back_to_the_connections_institution_when_the_provider_reports_none(self):
        # institution_name defaults to "" on AccountPayload -- some providers
        # or edge-case accounts may not report one.
        run = self.run_sync(fetch_result(accounts=[account_payload(institution_name="")]))

        self.assertEqual(run.status, SyncStatus.SUCCESS)
        self.assertEqual(Account.objects.get().institution_id, self.institution.id)

    def test_no_provider_name_and_no_fallback_fails_that_account_only(self):
        self.connection.institution = None
        self.connection.save()

        run = self.run_sync(fetch_result(accounts=[account_payload(institution_name="")]))

        self.assertEqual(run.status, SyncStatus.PARTIAL)
        self.assertEqual(run.accounts_synced, 0)
        self.assertEqual(Account.objects.count(), 0)


class ProviderNoticeTests(SyncTestCase):
    """SimpleFIN's top-level `errors` are usually a request-level remark (a
    date-range recommendation from a specific institution, say) rather than
    anything actually failing — the accounts and transactions still come
    back complete. Treating one as a hard failure would block
    last_synced_at from ever advancing, so the next sync re-requests the
    same window and re-triggers the same notice forever. A notice is
    recorded on the run, but the sync is still a success."""

    def test_a_provider_notice_alone_still_produces_a_successful_run(self):
        run = self.run_sync(fetch_result(errors=["Byline: recommended range is 45 days."]))

        self.assertEqual(run.status, SyncStatus.SUCCESS)
        self.assertIn("Byline", run.error_message)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_a_provider_notice_still_advances_last_synced_at(self):
        self.run_sync(fetch_result(errors=["recommended range is 45 days."]))

        self.connection.refresh_from_db()
        self.assertIsNotNone(self.connection.last_synced_at)
        self.assertEqual(self.connection.status, ConnectionStatus.ACTIVE)

    def test_a_second_sync_after_a_notice_uses_the_narrow_overlap_window(self):
        # The self-perpetuating-loop regression: if the first sync's notice
        # had blocked last_synced_at, this second call would still ask for
        # the full INITIAL_HISTORY_DAYS window instead of the 7-day overlap.
        self.run_sync(fetch_result(errors=["recommended range is 45 days."]))
        self.connection.refresh_from_db()

        since = default_since(self.connection)

        self.assertGreater(since, timezone.now().date() - timedelta(days=30))

    def test_a_real_account_failure_alongside_a_notice_still_reports_partial(self):
        result = fetch_result(
            accounts=[account_payload(provider_account_id="ACT-1")],
            transactions={"ACT-1": [transaction_payload(posted_on=None)]},
            errors=["recommended range is 45 days."],
        )

        run = self.run_sync(result)

        self.assertEqual(run.status, SyncStatus.PARTIAL)
        self.connection.refresh_from_db()
        self.assertIsNone(self.connection.last_synced_at)


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


class CredentialRedactionTests(TestCase):
    """Provider errors are rendered on the connection page.

    A SimpleFIN access URL carries its credential in the userinfo, so an
    exception echoing the URL would put that credential on screen.
    """

    def test_embedded_credentials_are_stripped(self):
        from finance.providers.base import redact

        cleaned = redact(
            "Max retries exceeded with url "
            "https://abc123:tok_9f8e7d@bridge.simplefin.org/simplefin/accounts"
        )

        self.assertNotIn("tok_9f8e7d", cleaned)
        self.assertNotIn("abc123", cleaned)
        self.assertIn("bridge.simplefin.org", cleaned)

    def test_ordinary_messages_are_untouched(self):
        from finance.providers.base import redact

        self.assertEqual(redact("could not reach host"), "could not reach host")

    def test_mark_failed_redacts_whatever_it_is_given(self):
        connection = AccountConnection.objects.create(
            institution=make_institution(), label="Byline", access_secret="x"
        )

        connection.mark_failed("failed on https://u:p4ssw0rd@bridge.simplefin.org/x")

        connection.refresh_from_db()
        self.assertNotIn("p4ssw0rd", connection.last_error)
        self.assertIn("<redacted>", connection.last_error)


class CrossSourceDuplicateTests(SyncTestCase):
    """A transaction imported by CSV and later reported by the provider is one
    transaction, not two.

    This is the bug that produced ten duplicates in production on a single
    day. upsert_transaction only looked up by provider_txn_id, which a CSV row
    does not have — and next_fingerprint() then stepped *past* the fingerprint
    collision that would otherwise have caught it, because its job is to allow
    genuinely repeated transactions through.
    """

    def csv_row(self, **kwargs):
        """A row shaped the way the CSV importer writes one: no provider id."""
        from finance.models import TransactionSource
        from finance.services.sync import next_fingerprint

        account = kwargs.pop("account")
        defaults = {
            "posted_on": date(2026, 4, 15),
            "amount": Decimal("-78.00"),
            "description_raw": "TST*THE BURROW TC",
        }
        defaults.update(kwargs)

        return Transaction.objects.create(
            account=account,
            provider_txn_id="",
            source=TransactionSource.CSV,
            # next_fingerprint, not build_fingerprint — this mirrors what
            # the CSV importer actually does, including walking the sequence
            # so two identical rows can coexist.
            fingerprint=next_fingerprint(
                account.id,
                defaults["posted_on"],
                defaults["amount"],
                defaults["description_raw"],
            ),
            **defaults,
        )

    def test_a_sync_claims_the_csv_row_instead_of_duplicating_it(self):
        self.run_sync(fetch_result(transactions={}))
        account = Account.objects.get()

        self.csv_row(account=account)

        self.run_sync(
            fetch_result(
                transactions={
                    "ACT-1": [
                        transaction_payload(
                            provider_txn_id="TRN-abc",
                            posted_on=date(2026, 4, 15),
                            amount=Decimal("-78.00"),
                            description="TST*THE BURROW TC",
                        )
                    ]
                }
            )
        )

        self.assertEqual(Transaction.objects.count(), 1)

        claimed = Transaction.objects.get()
        self.assertEqual(claimed.provider_txn_id, "TRN-abc")
        self.assertEqual(claimed.source, "provider")

    def test_claiming_keeps_a_category_already_confirmed_on_the_csv_row(self):
        """The reason to claim rather than skip: work done on the CSV row —
        a confirmed category — must not be thrown away."""
        from django.core.management import call_command

        call_command("seed_finance_categories", verbosity=0)
        from finance.models import Category, CategorySource

        self.run_sync(fetch_result(transactions={}))
        account = Account.objects.get()

        groceries = Category.objects.get(slug="food-groceries")
        row = self.csv_row(account=account)
        row.category = groceries
        row.category_source = CategorySource.MANUAL
        row.needs_review = False
        row.save()

        self.run_sync(
            fetch_result(
                transactions={
                    "ACT-1": [
                        transaction_payload(
                            provider_txn_id="TRN-abc",
                            posted_on=date(2026, 4, 15),
                            amount=Decimal("-78.00"),
                            description="TST*THE BURROW TC",
                        )
                    ]
                }
            )
        )

        claimed = Transaction.objects.get()
        self.assertEqual(claimed.category, groceries)
        self.assertEqual(claimed.category_source, CategorySource.MANUAL)

    def test_two_genuine_repeats_still_produce_two_rows(self):
        """The behavior claiming must not break: two identical coffees on one
        day are two transactions, and the provider reporting both must leave
        two rows, not one."""
        self.run_sync(fetch_result(transactions={}))
        account = Account.objects.get()

        self.csv_row(account=account, amount=Decimal("-4.75"), description_raw="STARBUCKS")
        self.csv_row(account=account, amount=Decimal("-4.75"), description_raw="STARBUCKS")

        self.assertEqual(Transaction.objects.count(), 2)

        self.run_sync(
            fetch_result(
                transactions={
                    "ACT-1": [
                        transaction_payload(
                            provider_txn_id=f"TRN-{n}",
                            posted_on=date(2026, 4, 15),
                            amount=Decimal("-4.75"),
                            description="STARBUCKS",
                        )
                        for n in ("a", "b")
                    ]
                }
            )
        )

        self.assertEqual(Transaction.objects.count(), 2)
        self.assertEqual(
            sorted(Transaction.objects.values_list("provider_txn_id", flat=True)),
            ["TRN-a", "TRN-b"],
        )

    def test_a_third_provider_copy_is_still_created(self):
        """Claiming consumes one unclaimed row per payload. If the provider
        reports three and only two were imported, the third is genuinely new."""
        self.run_sync(fetch_result(transactions={}))
        account = Account.objects.get()

        self.csv_row(account=account, amount=Decimal("-4.75"), description_raw="STARBUCKS")

        self.run_sync(
            fetch_result(
                transactions={
                    "ACT-1": [
                        transaction_payload(
                            provider_txn_id=f"TRN-{n}",
                            posted_on=date(2026, 4, 15),
                            amount=Decimal("-4.75"),
                            description="STARBUCKS",
                        )
                        for n in ("a", "b")
                    ]
                }
            )
        )

        self.assertEqual(Transaction.objects.count(), 2)

    def test_a_re_sync_after_claiming_does_not_duplicate(self):
        """The claimed row now carries the provider id, so the ordinary
        lookup finds it on every subsequent run."""
        self.run_sync(fetch_result(transactions={}))
        account = Account.objects.get()
        self.csv_row(account=account)

        payload = fetch_result(
            transactions={
                "ACT-1": [
                    transaction_payload(
                        provider_txn_id="TRN-abc",
                        posted_on=date(2026, 4, 15),
                        amount=Decimal("-78.00"),
                        description="TST*THE BURROW TC",
                    )
                ]
            }
        )

        self.run_sync(payload)
        self.run_sync(payload)
        self.run_sync(payload)

        self.assertEqual(Transaction.objects.count(), 1)


class SyncTrustsItsOwnPayloadTests(SyncTestCase):
    """The other half of the rule in test_csv_import.SourceOfTruthTests.

    A sync payload carrying three identical transactions with distinct
    provider ids is asserting three transactions happened. Claiming must
    never collapse them — it only ever consumes rows that no provider has
    claimed, which is exactly the CSV-imported case.
    """

    def three_identical(self):
        return fetch_result(
            transactions={
                "ACT-1": [
                    transaction_payload(
                        provider_txn_id=f"TRN-{n}",
                        amount=Decimal("-4.75"),
                        description="STARBUCKS",
                    )
                    for n in ("a", "b", "c")
                ]
            }
        )

    def test_one_payload_with_three_identical_transactions_creates_three(self):
        self.run_sync(self.three_identical())

        self.assertEqual(Transaction.objects.count(), 3)

    def test_re_syncing_the_same_payload_adds_nothing(self):
        self.run_sync(self.three_identical())
        self.run_sync(self.three_identical())

        self.assertEqual(Transaction.objects.count(), 3)

    def test_claiming_never_consumes_a_row_another_payload_already_claimed(self):
        """Three provider transactions and one prior CSV row is four assertions
        about reality minus one overlap — three transactions, not one."""
        self.run_sync(fetch_result(transactions={}))
        account = Account.objects.get()

        from finance.models import TransactionSource
        from finance.services.sync import next_fingerprint

        Transaction.objects.create(
            account=account,
            provider_txn_id="",
            source=TransactionSource.CSV,
            posted_on=date(2026, 4, 15),
            amount=Decimal("-4.75"),
            description_raw="STARBUCKS",
            fingerprint=next_fingerprint(
                account.id, date(2026, 4, 15), Decimal("-4.75"), "STARBUCKS"
            ),
        )

        self.run_sync(self.three_identical())

        self.assertEqual(Transaction.objects.count(), 3)
        self.assertEqual(
            Transaction.objects.filter(provider_txn_id="").count(),
            0,
            "the CSV row should have been claimed, not left orphaned alongside a new one",
        )
