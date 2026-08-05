"""Working out what a CSV's columns mean, so a person only has to confirm.

Every institution exports a different shape, and the two that matter most here
— Northwestern Mutual and CrossCountry Mortgage — cannot be aggregated at all,
so their files are the only way that data ever arrives.

The rule throughout: guess confidently, never act on the guess alone. Detection
proposes, a human confirms once per institution, and the confirmed mapping is
saved and replayed. A silently-wrong column mapping is far worse than an
unmapped one, because it lands plausible numbers in the wrong place.
"""

import csv
import re
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation

SAMPLE_SIZE = 12

# Header fragments that identify a field, best guess first. Matched against a
# lowercased header with punctuation stripped.
HEADER_HINTS = {
    "posted_on": [
        "posted date", "post date", "transaction date", "trans date",
        "posted", "date",
    ],
    "amount": ["amount", "transaction amount", "value"],
    "debit": ["debit", "withdrawal", "money out", "charges"],
    "credit": ["credit", "deposit", "money in", "payments"],
    "description": [
        "description", "payee", "merchant", "name", "memo", "details",
        "transaction",
    ],
    "merchant": ["payee", "merchant", "name"],
    "external_id": ["transaction id", "reference", "id"],
    "as_of": ["as of", "date", "statement date", "balance date"],
    "current": ["balance", "current balance", "principal", "cash value", "value"],
    "available": ["available", "available balance"],
    "pay_date": ["pay date", "check date", "period end", "date"],
    "employer": ["employer", "company"],
    "gross": ["gross", "gross pay", "total earnings"],
    "net": ["net", "net pay", "take home"],
}

DATE_FORMATS = [
    "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%Y/%m/%d",
    "%m-%d-%Y", "%d-%m-%Y", "%b %d, %Y", "%d %b %Y", "%Y%m%d",
    "%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
]

AMOUNT_CLEAN = re.compile(r"[^\d\-.\(\)]")


def normalize_header(header: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", (header or "").casefold()).strip()


def sniff(raw_bytes: bytes):
    """Read a CSV's headers and first rows, tolerating preamble lines.

    Several institutions put a title or an account summary above the real
    header row, so the header is taken to be the first line whose column count
    matches the bulk of the file.
    """
    text = raw_bytes.decode("utf-8-sig", errors="replace")
    lines = [line for line in text.splitlines() if line.strip()]

    if not lines:
        return [], [], 0

    try:
        dialect = csv.Sniffer().sniff("\n".join(lines[:20]))
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","

    parsed = list(csv.reader(lines, delimiter=delimiter))
    widths = Counter(len(row) for row in parsed)

    # Most common width wins, but ties break toward the *wider* row. A short
    # file with three preamble lines and three data rows ties 3-to-3, and
    # picking the one-column preamble would swallow the whole statement.
    body_width = max(widths.items(), key=lambda item: (item[1], item[0]))[0]

    header_index = next(
        (i for i, row in enumerate(parsed) if len(row) == body_width and _looks_like_header(row)),
        0,
    )

    headers = [cell.strip() for cell in parsed[header_index]]
    rows = [
        dict(zip(headers, row))
        for row in parsed[header_index + 1 : header_index + 1 + SAMPLE_SIZE]
        if len(row) == body_width
    ]

    return headers, rows, header_index


def _looks_like_header(row):
    """A header row is mostly non-numeric text."""
    non_numeric = sum(1 for cell in row if cell.strip() and not _is_numberish(cell))
    return non_numeric >= max(2, len(row) // 2)


def _is_numberish(value):
    try:
        Decimal(AMOUNT_CLEAN.sub("", str(value)) or "x")
        return True
    except InvalidOperation:
        return False


def parse_amount(value):
    """Read a currency cell, handling $, commas, and (parenthesized) negatives."""
    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    negative = text.startswith("(") and text.endswith(")")
    cleaned = AMOUNT_CLEAN.sub("", text).replace("(", "").replace(")", "")

    if not cleaned or cleaned in {"-", "."}:
        return None

    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None

    return -amount if negative else amount


def detect_date_format(values):
    """The first format that parses every non-empty sample.

    Requiring all of them rules out ambiguity: 03/04/2026 alone could be March
    or April, but a sample containing 13/04/2026 settles it.
    """
    candidates = [v for v in values if v and str(v).strip()]

    if not candidates:
        return ""

    for fmt in DATE_FORMATS:
        if all(_parses(value, fmt) for value in candidates):
            return fmt

    return ""


def _parses(value, fmt):
    try:
        datetime.strptime(str(value).strip(), fmt)
        return True
    except (ValueError, TypeError):
        return False


def parse_date(value, fmt=""):
    text = str(value or "").strip()

    if not text:
        return None

    for candidate in ([fmt] if fmt else []) + DATE_FORMATS:
        if not candidate:
            continue
        try:
            return datetime.strptime(text, candidate).date()
        except ValueError:
            continue

    return None


def suggest_mapping(headers, rows, record_type="transactions"):
    """Propose a column mapping and say how confident each guess is.

    Returns {field: {"column": header, "confidence": float}} so the UI can
    show the low-confidence guesses as the ones needing a second look.
    """
    wanted = {
        "transactions": ["posted_on", "amount", "debit", "credit", "description", "merchant", "external_id"],
        "balances": ["as_of", "current", "available"],
        "paycheck": ["pay_date", "employer", "gross", "net"],
    }.get(record_type, [])

    normalized = {header: normalize_header(header) for header in headers}
    suggestion = {}
    claimed = set()

    for field in wanted:
        best = _best_header(field, normalized, claimed)

        if best:
            header, confidence = best
            suggestion[field] = {"column": header, "confidence": confidence}
            # A column means one thing; without this, "date" would be claimed
            # by both posted_on and as_of.
            claimed.add(header)

    return suggestion


def _best_header(field, normalized, claimed):
    hints = HEADER_HINTS.get(field, [])

    for rank, hint in enumerate(hints):
        for header, normal in normalized.items():
            if header in claimed:
                continue

            if normal == hint:
                return header, 1.0

            if hint in normal:
                # Later hints are weaker signals; a bare "date" matching
                # posted_on is a good guess, not a certainty.
                return header, max(0.5, 0.95 - rank * 0.1)

    return None


def detect_amount_convention(suggestion, rows):
    """Whether the file uses one signed column or separate debit/credit ones."""
    from ..models import AmountConvention

    if "debit" in suggestion or "credit" in suggestion:
        return AmountConvention.DEBIT_CREDIT

    column = (suggestion.get("amount") or {}).get("column")

    if not column:
        return AmountConvention.SIGNED

    amounts = [parse_amount(row.get(column)) for row in rows]
    amounts = [a for a in amounts if a is not None]

    # A statement of only positive amounts in a single column almost always
    # means positive-is-a-charge. Flagged rather than assumed — this is the
    # single most damaging thing to get wrong, so the UI asks.
    if amounts and all(amount >= 0 for amount in amounts):
        return AmountConvention.SIGNED_INVERTED

    return AmountConvention.SIGNED
