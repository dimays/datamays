"""Staging, previewing, and committing an uploaded file.

Rows are parsed and checked against what is already in the ledger *before*
anything is written, so a wrong column mapping shows up on screen as a preview
full of nonsense rather than as quietly corrupted dashboards.
"""

import csv
import io
from decimal import Decimal

from django.db import transaction as db_transaction
from django.utils import timezone

from ..models import (
    AmountConvention,
    BalanceSource,
    ImportBatch,
    ImportRow,
    ImportStatus,
    RecordType,
    RowStatus,
    Transaction,
    TransactionSource,
)
from .detection import parse_amount, parse_date, sniff
from .sync import next_fingerprint, record_balance_snapshot


class ImportError_(Exception):
    """A file could not be processed at all."""


def stage_upload(batch: ImportBatch) -> ImportBatch:
    """Read the file, record its shape, and propose a mapping."""
    from .detection import detect_amount_convention, detect_date_format, suggest_mapping

    headers, sample_rows, skip_rows = sniff(batch.raw_content.encode())

    if not headers:
        batch.status = ImportStatus.FAILED
        batch.error_message = "That file has no readable header row."
        batch.save()
        raise ImportError_(batch.error_message)

    suggestion = suggest_mapping(headers, sample_rows, batch.record_type)

    date_field = {"transactions": "posted_on", "balances": "as_of", "paycheck": "pay_date"}[
        batch.record_type
    ]
    date_column = (suggestion.get(date_field) or {}).get("column")

    batch.detected_headers = headers
    batch.sample_rows = sample_rows
    batch.suggested_map = {
        "columns": suggestion,
        "skip_rows": skip_rows,
        "date_format": detect_date_format(
            [row.get(date_column) for row in sample_rows] if date_column else []
        ),
        "amount_convention": detect_amount_convention(suggestion, sample_rows),
    }
    batch.status = ImportStatus.NEEDS_MAPPING
    batch.save()

    return batch


def _read_rows(batch, skip_rows):
    lines = [line for line in batch.raw_content.splitlines() if line.strip()]
    reader = csv.DictReader(io.StringIO("\n".join(lines[skip_rows:])))

    return list(reader)


def resolve_amount(row, column_map, convention):
    """Turn a row's amount cell(s) into our signed convention."""
    if convention == AmountConvention.DEBIT_CREDIT:
        debit = parse_amount(row.get(column_map.get("debit", ""))) or Decimal("0")
        credit = parse_amount(row.get(column_map.get("credit", ""))) or Decimal("0")

        if not debit and not credit:
            return None

        # Debits are money out however the file writes them.
        return abs(credit) - abs(debit)

    amount = parse_amount(row.get(column_map.get("amount", "")))

    if amount is None:
        return None

    return -amount if convention == AmountConvention.SIGNED_INVERTED else amount


@db_transaction.atomic
def parse_batch(batch: ImportBatch, *, column_map, date_format="", amount_convention=None, skip_rows=None):
    """Stage every row with its parse result and duplicate status."""
    batch.rows.all().delete()

    convention = amount_convention or AmountConvention.SIGNED

    # Fall back to what staging detected, so a caller cannot accidentally
    # re-read a file's preamble as data by forgetting to pass this through.
    if skip_rows is None:
        skip_rows = (batch.suggested_map or {}).get("skip_rows", 0)

    rows = _read_rows(batch, skip_rows)

    staged = []
    occurrences = {}
    counts = {"ok": 0, "duplicate": 0, "error": 0}

    for index, row in enumerate(rows, start=1):
        parsed, error = _parse_row(batch, row, column_map, date_format, convention)

        if error:
            status = RowStatus.ERROR
            counts["error"] += 1
        elif _is_duplicate(batch, parsed, occurrences):
            status = RowStatus.DUPLICATE
            counts["duplicate"] += 1
        else:
            status = RowStatus.OK
            counts["ok"] += 1

        staged.append(
            ImportRow(
                batch=batch,
                row_number=index,
                raw=row,
                parsed=_serializable(parsed),
                status=status,
                error_message=error or "",
            )
        )

    ImportRow.objects.bulk_create(staged)

    batch.row_count = len(rows)
    batch.created_count = counts["ok"]
    batch.duplicate_count = counts["duplicate"]
    batch.error_count = counts["error"]
    batch.status = ImportStatus.PREVIEW
    batch.save()

    return batch


def _parse_row(batch, row, column_map, date_format, convention):
    if batch.record_type == RecordType.TRANSACTIONS:
        posted_on = parse_date(row.get(column_map.get("posted_on", "")), date_format)
        amount = resolve_amount(row, column_map, convention)
        description = str(row.get(column_map.get("description", "")) or "").strip()

        if posted_on is None:
            return {}, "Could not read a date from the mapped column."
        if amount is None:
            return {}, "Could not read an amount from the mapped column."
        if not description:
            return {}, "No description in the mapped column."

        return (
            {
                "posted_on": posted_on,
                "amount": amount,
                "description": description[:500],
                "merchant": str(row.get(column_map.get("merchant", "")) or "").strip()[:160],
            },
            None,
        )

    if batch.record_type == RecordType.BALANCES:
        as_of = parse_date(row.get(column_map.get("as_of", "")), date_format)
        current = parse_amount(row.get(column_map.get("current", "")))

        if as_of is None:
            return {}, "Could not read a date from the mapped column."
        if current is None:
            return {}, "Could not read a balance from the mapped column."

        return (
            {
                "as_of": as_of,
                "current": current,
                "available": parse_amount(row.get(column_map.get("available", ""))),
            },
            None,
        )

    # Paychecks
    pay_date = parse_date(row.get(column_map.get("pay_date", "")), date_format)
    gross = parse_amount(row.get(column_map.get("gross", "")))
    net = parse_amount(row.get(column_map.get("net", "")))

    if pay_date is None:
        return {}, "Could not read a pay date from the mapped column."
    if gross is None or net is None:
        return {}, "Could not read gross and net pay from the mapped columns."

    deductions = {
        key.split(":", 1)[1]: parse_amount(row.get(column))
        for key, column in column_map.items()
        if key.startswith("deduction:") and column
    }

    return (
        {
            "pay_date": pay_date,
            "employer": str(row.get(column_map.get("employer", "")) or "").strip()[:160],
            "gross": gross,
            "net": net,
            "deductions": {k: v for k, v in deductions.items() if v},
        },
        None,
    )


def _is_duplicate(batch, parsed, occurrences):
    """Whether this row is already in the ledger.

    Counting matters here. If the file has three identical $4.75 coffees and
    the ledger already holds two, the first two rows are duplicates and the
    third is new — so this compares the row's occurrence index within the file
    against how many matching rows already exist, rather than treating any
    match as a duplicate. Getting this wrong drops real transactions silently.
    """
    if not parsed or batch.account_id is None:
        return False

    if batch.record_type == RecordType.TRANSACTIONS:
        key = (parsed["posted_on"], parsed["amount"], parsed["description"].casefold())

        index_in_file = occurrences.get(key, 0)
        occurrences[key] = index_in_file + 1

        already_in_ledger = Transaction.objects.filter(
            account_id=batch.account_id,
            posted_on=parsed["posted_on"],
            amount=parsed["amount"],
            description_raw__iexact=parsed["description"],
        ).count()

        return index_in_file < already_in_ledger

    if batch.record_type == RecordType.BALANCES:
        from ..models import AccountBalanceSnapshot

        # One balance per account per day; a repeat is an overwrite, not a
        # new data point.
        return AccountBalanceSnapshot.objects.filter(
            account_id=batch.account_id, as_of=parsed["as_of"]
        ).exists()

    if batch.record_type == RecordType.PAYCHECK:
        from ..models import Paycheck

        return Paycheck.objects.filter(
            user=batch.uploaded_by,
            employer=parsed.get("employer") or batch.institution.name,
            pay_date=parsed["pay_date"],
        ).exists()

    return False


def _serializable(parsed):
    out = {}

    for key, value in (parsed or {}).items():
        if hasattr(value, "isoformat"):
            out[key] = value.isoformat()
        elif isinstance(value, Decimal):
            out[key] = str(value)
        elif isinstance(value, dict):
            out[key] = {k: str(v) for k, v in value.items()}
        else:
            out[key] = value

    return out


@db_transaction.atomic
def commit_batch(batch: ImportBatch) -> ImportBatch:
    """Write the rows that parsed cleanly and are not already in the ledger."""
    if batch.is_committed:
        raise ImportError_("This file has already been imported.")

    created = 0

    for row in batch.rows.filter(status=RowStatus.OK).select_related("batch"):
        if batch.record_type == RecordType.TRANSACTIONS:
            created += _commit_transaction(batch, row)
        elif batch.record_type == RecordType.BALANCES:
            created += _commit_balance(batch, row)
        else:
            created += _commit_paycheck(batch, row)

    batch.created_count = created
    batch.status = ImportStatus.COMMITTED
    batch.committed_at = timezone.now()
    batch.save()

    if batch.mapping_id:
        batch.mapping.times_used += 1
        batch.mapping.last_used_at = timezone.now()
        batch.mapping.save(update_fields=["times_used", "last_used_at", "updated_at"])

    return batch


def _commit_transaction(batch, row):
    from datetime import date as date_cls

    posted_on = date_cls.fromisoformat(row.parsed["posted_on"])
    amount = Decimal(row.parsed["amount"])
    description = row.parsed["description"]

    transaction = Transaction.objects.create(
        account_id=batch.account_id,
        fingerprint=next_fingerprint(batch.account_id, posted_on, amount, description),
        posted_on=posted_on,
        amount=amount,
        description_raw=description,
        merchant=row.parsed.get("merchant", ""),
        source=TransactionSource.CSV,
        import_batch=batch,
    )

    row.transaction = transaction
    row.save(update_fields=["transaction"])

    return 1


def _commit_balance(batch, row):
    from datetime import date as date_cls

    available = row.parsed.get("available")

    record_balance_snapshot(
        batch.account,
        as_of=date_cls.fromisoformat(row.parsed["as_of"]),
        current=Decimal(row.parsed["current"]),
        available=Decimal(available) if available else None,
        source=BalanceSource.CSV,
    )

    return 1


def _commit_paycheck(batch, row):
    from datetime import date as date_cls

    from ..models import DeductionKind, Paycheck, PaycheckDeduction

    paycheck, created = Paycheck.objects.get_or_create(
        user=batch.uploaded_by,
        employer=row.parsed.get("employer") or batch.institution.name,
        pay_date=date_cls.fromisoformat(row.parsed["pay_date"]),
        defaults={
            "gross": Decimal(row.parsed["gross"]),
            "net": Decimal(row.parsed["net"]),
            "deposit_account": batch.account,
            "import_batch": batch,
        },
    )

    if not created:
        return 0

    valid_kinds = set(DeductionKind.values)

    for kind, amount in (row.parsed.get("deductions") or {}).items():
        if kind in valid_kinds and amount:
            PaycheckDeduction.objects.create(
                paycheck=paycheck, kind=kind, amount=Decimal(amount)
            )

    return 1
