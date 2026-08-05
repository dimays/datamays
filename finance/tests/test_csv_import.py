"""CSV detection and import.

Fixtures imitate the export shapes real institutions actually produce —
preamble lines, parenthesized negatives, separate debit/credit columns, and
statements where every amount is positive.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from finance.dates import to_household_date
from finance.models import (
    AccountBalanceSnapshot,
    AmountConvention,
    ImportBatch,
    ImportStatus,
    Paycheck,
    RecordType,
    RowStatus,
    Transaction,
)
from finance.services.detection import (
    detect_amount_convention,
    detect_date_format,
    parse_amount,
    parse_date,
    sniff,
    suggest_mapping,
)
from finance.services.importer import commit_batch, parse_batch, stage_upload

from .factories import make_account, make_institution, make_user

SIMPLE_CSV = b"""Posted Date,Description,Amount
04/15/2026,MARIANOS #1234 CHICAGO IL,-42.50
04/16/2026,ACME PAYROLL DIRECT DEP,2500.00
"""

PREAMBLE_CSV = b"""Byline Bank
Account Statement
Generated 2026-04-20

Transaction Date,Payee,Debit,Credit
04/15/2026,Marianos,42.50,
04/16/2026,Acme Payroll,,2500.00
"""

POSITIVE_ONLY_CSV = b"""Date,Merchant,Amount
04/15/2026,MARIANOS,42.50
04/16/2026,SHELL OIL,38.10
"""

PARENTHESIZED_CSV = b"""Date,Description,Amount
04/15/2026,MARIANOS,($42.50)
04/16/2026,REFUND,"$1,200.00"
"""


class ParsingTests(TestCase):
    def test_currency_formatting_is_stripped(self):
        self.assertEqual(parse_amount("$1,234.56"), Decimal("1234.56"))
        self.assertEqual(parse_amount("-42.50"), Decimal("-42.50"))

    def test_parenthesized_amounts_are_negative(self):
        # Accounting convention: (42.50) means minus 42.50.
        self.assertEqual(parse_amount("($42.50)"), Decimal("-42.50"))

    def test_blank_and_nonsense_cells_return_none_rather_than_zero(self):
        # Returning 0 would silently import a real transaction as free.
        for value in ["", "   ", None, "n/a", "-"]:
            with self.subTest(value=value):
                self.assertIsNone(parse_amount(value))

    def test_date_format_detection_requires_every_sample_to_parse(self):
        self.assertEqual(detect_date_format(["04/15/2026", "12/31/2026"]), "%m/%d/%Y")
        self.assertEqual(detect_date_format(["2026-04-15", "2026-12-31"]), "%Y-%m-%d")

    def test_an_unambiguous_day_first_sample_is_detected(self):
        # 13 cannot be a month, which settles the ambiguity.
        self.assertEqual(detect_date_format(["13/04/2026", "01/05/2026"]), "%d/%m/%Y")

    def test_unparseable_dates_yield_no_format_rather_than_a_wrong_guess(self):
        self.assertEqual(detect_date_format(["last tuesday"]), "")

    def test_parse_date_falls_back_across_known_formats(self):
        self.assertEqual(parse_date("04/15/2026"), date(2026, 4, 15))
        self.assertIsNone(parse_date("not a date"))


class SniffTests(TestCase):
    def test_a_plain_file_is_read(self):
        headers, rows, skip = sniff(SIMPLE_CSV)

        self.assertEqual(headers, ["Posted Date", "Description", "Amount"])
        self.assertEqual(len(rows), 2)
        self.assertEqual(skip, 0)

    def test_preamble_lines_are_skipped_to_find_the_real_header(self):
        headers, rows, skip = sniff(PREAMBLE_CSV)

        self.assertEqual(headers, ["Transaction Date", "Payee", "Debit", "Credit"])
        self.assertGreater(skip, 0)
        self.assertEqual(len(rows), 2)

    def test_an_empty_file_is_handled(self):
        self.assertEqual(sniff(b""), ([], [], 0))


class SuggestionTests(TestCase):
    def test_obvious_columns_are_matched_confidently(self):
        headers, rows, _ = sniff(SIMPLE_CSV)
        suggestion = suggest_mapping(headers, rows)

        self.assertEqual(suggestion["posted_on"]["column"], "Posted Date")
        self.assertEqual(suggestion["amount"]["column"], "Amount")
        self.assertEqual(suggestion["description"]["column"], "Description")

    def test_a_column_is_only_claimed_once(self):
        headers, rows, _ = sniff(SIMPLE_CSV)
        suggestion = suggest_mapping(headers, rows)

        claimed = [entry["column"] for entry in suggestion.values()]
        self.assertEqual(len(claimed), len(set(claimed)))

    def test_debit_and_credit_columns_are_recognized(self):
        headers, rows, _ = sniff(PREAMBLE_CSV)
        suggestion = suggest_mapping(headers, rows)

        self.assertEqual(suggestion["debit"]["column"], "Debit")
        self.assertEqual(suggestion["credit"]["column"], "Credit")
        self.assertEqual(
            detect_amount_convention(suggestion, rows), AmountConvention.DEBIT_CREDIT
        )

    def test_an_all_positive_statement_is_flagged_for_confirmation(self):
        # The most damaging thing to get wrong, so it is surfaced, not assumed.
        headers, rows, _ = sniff(POSITIVE_ONLY_CSV)
        suggestion = suggest_mapping(headers, rows)

        self.assertEqual(
            detect_amount_convention(suggestion, rows), AmountConvention.SIGNED_INVERTED
        )

    def test_a_signed_statement_is_left_alone(self):
        headers, rows, _ = sniff(SIMPLE_CSV)
        suggestion = suggest_mapping(headers, rows)

        self.assertEqual(
            detect_amount_convention(suggestion, rows), AmountConvention.SIGNED
        )


class ImportBatchTestCase(TestCase):
    def setUp(self):
        self.user = make_user()
        self.institution = make_institution()
        self.account = make_account(self.institution)

    def make_batch(self, content, record_type=RecordType.TRANSACTIONS, name="export.csv"):
        batch = ImportBatch.objects.create(
            uploaded_by=self.user,
            institution=self.institution,
            account=self.account,
            record_type=record_type,
            original_filename=name,
            raw_content=content.decode(),
        )
        return stage_upload(batch)

    def columns(self, batch):
        return {
            field: entry["column"]
            for field, entry in batch.suggested_map["columns"].items()
        }


class StagingTests(ImportBatchTestCase):
    def test_staging_proposes_a_mapping_without_writing_anything(self):
        batch = self.make_batch(SIMPLE_CSV)

        self.assertEqual(batch.status, ImportStatus.NEEDS_MAPPING)
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertIn("posted_on", batch.suggested_map["columns"])

    def test_rows_are_previewed_before_commit(self):
        batch = self.make_batch(SIMPLE_CSV)
        batch = parse_batch(batch, column_map=self.columns(batch), date_format="%m/%d/%Y")

        self.assertEqual(batch.status, ImportStatus.PREVIEW)
        self.assertEqual(batch.row_count, 2)
        self.assertEqual(batch.created_count, 2)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_committing_writes_the_rows(self):
        batch = self.make_batch(SIMPLE_CSV)
        batch = parse_batch(batch, column_map=self.columns(batch), date_format="%m/%d/%Y")
        commit_batch(batch)

        self.assertEqual(Transaction.objects.count(), 2)

        grocery = Transaction.objects.get(amount=Decimal("-42.50"))
        self.assertEqual(grocery.posted_on, date(2026, 4, 15))
        self.assertEqual(grocery.source, "csv")

    def test_debit_and_credit_columns_produce_correct_signs(self):
        batch = self.make_batch(PREAMBLE_CSV)
        batch = parse_batch(
            batch,
            column_map=self.columns(batch),
            date_format="%m/%d/%Y",
            amount_convention=AmountConvention.DEBIT_CREDIT,
            skip_rows=batch.suggested_map["skip_rows"],
        )
        commit_batch(batch)

        amounts = sorted(t.amount for t in Transaction.objects.all())
        self.assertEqual(amounts, [Decimal("-42.50"), Decimal("2500.00")])

    def test_an_inverted_statement_is_flipped_on_import(self):
        batch = self.make_batch(POSITIVE_ONLY_CSV)
        batch = parse_batch(
            batch,
            column_map=self.columns(batch),
            date_format="%m/%d/%Y",
            amount_convention=AmountConvention.SIGNED_INVERTED,
        )
        commit_batch(batch)

        self.assertTrue(all(t.amount < 0 for t in Transaction.objects.all()))

    def test_parenthesized_and_comma_amounts_import_correctly(self):
        batch = self.make_batch(PARENTHESIZED_CSV)
        batch = parse_batch(batch, column_map=self.columns(batch), date_format="%m/%d/%Y")
        commit_batch(batch)

        amounts = sorted(t.amount for t in Transaction.objects.all())
        self.assertEqual(amounts, [Decimal("-42.50"), Decimal("1200.00")])


class DuplicateTests(ImportBatchTestCase):
    def import_file(self, content=SIMPLE_CSV):
        batch = self.make_batch(content)
        batch = parse_batch(batch, column_map=self.columns(batch), date_format="%m/%d/%Y")
        return commit_batch(batch)

    def test_reimporting_the_same_file_adds_nothing(self):
        self.import_file()
        second = self.import_file()

        self.assertEqual(Transaction.objects.count(), 2)
        self.assertEqual(second.created_count, 0)
        self.assertEqual(second.duplicate_count, 2)

    def test_an_overlapping_export_only_adds_the_new_rows(self):
        self.import_file()

        overlapping = b"""Posted Date,Description,Amount
04/16/2026,ACME PAYROLL DIRECT DEP,2500.00
04/17/2026,SHELL OIL 4455,-38.10
"""
        batch = self.import_file(overlapping)

        self.assertEqual(batch.created_count, 1)
        self.assertEqual(batch.duplicate_count, 1)
        self.assertEqual(Transaction.objects.count(), 3)

    def test_genuinely_repeated_transactions_are_not_collapsed(self):
        # Three identical coffees in one day are three purchases.
        repeated = b"""Posted Date,Description,Amount
04/15/2026,STARBUCKS,-4.75
04/15/2026,STARBUCKS,-4.75
04/15/2026,STARBUCKS,-4.75
"""
        batch = self.import_file(repeated)

        self.assertEqual(batch.created_count, 3)
        self.assertEqual(Transaction.objects.count(), 3)

    def test_a_partial_reimport_of_repeats_adds_only_the_missing_one(self):
        self.import_file(
            b"""Posted Date,Description,Amount
04/15/2026,STARBUCKS,-4.75
04/15/2026,STARBUCKS,-4.75
"""
        )

        batch = self.import_file(
            b"""Posted Date,Description,Amount
04/15/2026,STARBUCKS,-4.75
04/15/2026,STARBUCKS,-4.75
04/15/2026,STARBUCKS,-4.75
"""
        )

        self.assertEqual(batch.created_count, 1)
        self.assertEqual(batch.duplicate_count, 2)
        self.assertEqual(Transaction.objects.count(), 3)


class BadRowTests(ImportBatchTestCase):
    def test_unparseable_rows_are_flagged_not_dropped_silently(self):
        broken = b"""Posted Date,Description,Amount
04/15/2026,MARIANOS,-42.50
not a date,BROKEN ROW,-10.00
04/17/2026,NO AMOUNT,
"""
        batch = self.make_batch(broken)
        batch = parse_batch(batch, column_map=self.columns(batch), date_format="%m/%d/%Y")

        self.assertEqual(batch.error_count, 2)
        self.assertEqual(batch.created_count, 1)

        errors = batch.rows.filter(status=RowStatus.ERROR)
        self.assertTrue(all(row.error_message for row in errors))

    def test_only_clean_rows_are_committed(self):
        broken = b"""Posted Date,Description,Amount
04/15/2026,MARIANOS,-42.50
not a date,BROKEN ROW,-10.00
"""
        batch = self.make_batch(broken)
        batch = parse_batch(batch, column_map=self.columns(batch), date_format="%m/%d/%Y")
        commit_batch(batch)

        self.assertEqual(Transaction.objects.count(), 1)

    def test_committing_twice_is_refused(self):
        from finance.services.importer import ImportError_

        batch = self.make_batch(SIMPLE_CSV)
        batch = parse_batch(batch, column_map=self.columns(batch), date_format="%m/%d/%Y")
        commit_batch(batch)

        with self.assertRaises(ImportError_):
            commit_batch(batch)


class BalanceAndPaycheckImportTests(ImportBatchTestCase):
    def test_balance_history_imports_for_a_manual_account(self):
        # This is how Northwestern Mutual and the mortgage get their history.
        content = b"""Statement Date,Cash Value
2026-01-31,18450.00
2026-02-28,18720.00
"""
        batch = self.make_batch(content, record_type=RecordType.BALANCES)
        batch = parse_batch(
            batch, column_map=self.columns(batch), date_format="%Y-%m-%d"
        )
        commit_batch(batch)

        self.assertEqual(AccountBalanceSnapshot.objects.count(), 2)
        self.assertEqual(
            AccountBalanceSnapshot.objects.get(as_of=date(2026, 2, 28)).current,
            Decimal("18720.00"),
        )

    def test_importing_balances_updates_the_accounts_cached_balance(self):
        """The reported bug: imported balances showed on the Charts tab (built
        from snapshots) but the homepage kept reading a stale — in practice
        None — Account.current_balance, because nothing wrote it."""
        content = b"""Statement Date,Cash Value
2026-01-31,18450.00
2026-02-28,18720.00
"""
        batch = self.make_batch(content, record_type=RecordType.BALANCES)
        batch = parse_batch(
            batch, column_map=self.columns(batch), date_format="%Y-%m-%d"
        )
        commit_batch(batch)

        self.account.refresh_from_db()
        self.assertEqual(self.account.current_balance, Decimal("18720.00"))
        self.assertIsNotNone(self.account.balance_as_of)
        self.assertEqual(
            to_household_date(self.account.balance_as_of), date(2026, 2, 28)
        )

    def test_the_cached_balance_follows_the_newest_row_not_the_last_parsed(self):
        """A file can hold history, or rows out of order. The cache must end
        up on the most recent reading either way."""
        content = b"""Statement Date,Cash Value
2026-02-28,18720.00
2026-01-31,18450.00
"""
        batch = self.make_batch(content, record_type=RecordType.BALANCES)
        batch = parse_batch(
            batch, column_map=self.columns(batch), date_format="%Y-%m-%d"
        )
        commit_batch(batch)

        self.account.refresh_from_db()
        self.assertEqual(self.account.current_balance, Decimal("18720.00"))

    def test_importing_older_history_does_not_regress_a_newer_balance(self):
        """Backfilling 2025 statements must not drag the homepage back in
        time — the cache tracks the newest snapshot, not the newest import."""
        AccountBalanceSnapshot.objects.create(
            account=self.account, as_of=date(2026, 6, 30), current=Decimal("21000.00")
        )

        content = b"""Statement Date,Cash Value
2025-01-31,9000.00
2025-02-28,9500.00
"""
        batch = self.make_batch(content, record_type=RecordType.BALANCES)
        batch = parse_batch(
            batch, column_map=self.columns(batch), date_format="%Y-%m-%d"
        )
        commit_batch(batch)

        self.account.refresh_from_db()
        self.assertEqual(self.account.current_balance, Decimal("21000.00"))

    def test_a_transactions_import_leaves_the_cached_balance_alone(self):
        """Only a balances file carries a balance. A transactions import must
        not invent one."""
        self.account.current_balance = Decimal("500.00")
        self.account.save(update_fields=["current_balance"])

        batch = self.make_batch(SIMPLE_CSV)
        batch = parse_batch(batch, column_map=self.columns(batch), date_format="%m/%d/%Y")
        commit_batch(batch)

        self.account.refresh_from_db()
        self.assertEqual(self.account.current_balance, Decimal("500.00"))

    def test_paychecks_import_with_their_deductions(self):
        content = b"""Pay Date,Employer,Gross Pay,Net Pay,Federal Tax,FICA,Retirement
2026-04-15,Acme,5000.00,3400.00,800.00,350.00,200.00
"""
        batch = self.make_batch(content, record_type=RecordType.PAYCHECK)

        column_map = self.columns(batch) | {
            "deduction:federal_tax": "Federal Tax",
            "deduction:fica": "FICA",
            "deduction:retirement": "Retirement",
        }

        batch = parse_batch(batch, column_map=column_map, date_format="%Y-%m-%d")
        commit_batch(batch)

        paycheck = Paycheck.objects.get()
        self.assertEqual(paycheck.gross, Decimal("5000.00"))
        self.assertEqual(paycheck.deductions.count(), 3)
        self.assertEqual(paycheck.retained_deductions, Decimal("200.00"))

    def test_reimporting_a_paycheck_does_not_double_it(self):
        content = b"""Pay Date,Employer,Gross Pay,Net Pay
2026-04-15,Acme,5000.00,3400.00
"""
        for _ in range(2):
            batch = self.make_batch(content, record_type=RecordType.PAYCHECK)
            batch = parse_batch(
                batch, column_map=self.columns(batch), date_format="%Y-%m-%d"
            )
            commit_batch(batch)

        self.assertEqual(Paycheck.objects.count(), 1)


class ColumnMapTests(TestCase):
    """"amount_convention" starts with "amount" and was stored as a column."""

    def test_only_real_field_names_are_kept(self):
        from finance.views.imports import OPTIONAL_FIELDS, REQUIRED_FIELDS

        allowed = set(
            REQUIRED_FIELDS[RecordType.TRANSACTIONS]
            + OPTIONAL_FIELDS[RecordType.TRANSACTIONS]
        )

        post = {
            "csrfmiddlewaretoken": "abc",
            "posted_on": "Transaction Date",
            "description": "Payee",
            "amount_convention": "debit_credit",
            "date_format": "%m/%d/%Y",
            "mapping_name": "Byline default",
        }

        column_map = {k: v for k, v in post.items() if k in allowed and v}

        self.assertEqual(
            column_map, {"posted_on": "Transaction Date", "description": "Payee"}
        )
        self.assertNotIn("amount_convention", column_map)
