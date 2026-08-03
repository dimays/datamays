"""Pulling provider data into the ledger.

Designed to be safe to run repeatedly and at any hour: every write is an
upsert keyed on a stable identity, so a re-run after a crash, a double-fire of
the scheduler, or an overlapping backfill window all converge on the same
rows rather than duplicating them.

Deliberately framework-agnostic — plain functions over Django models, with no
knowledge of management commands, requests, or a scheduler. Wrapping these in
Prefect later means calling them from a flow, not rewriting them.
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction as db_transaction
from django.utils import timezone

from ..models import (
    LIABILITY_TYPES,
    Account,
    AccountBalanceSnapshot,
    AccountConnection,
    AccountType,
    BalanceSource,
    SyncRun,
    SyncStatus,
    SyncTrigger,
    Transaction,
    TransactionSource,
    build_fingerprint,
)
from ..providers.base import ProviderAuthError, ProviderError
from ..providers.registry import get_adapter

logger = logging.getLogger(__name__)

# How far back to re-read on a routine sync. Institutions amend and back-date
# postings for days after the fact, so only ever asking for "since last sync"
# quietly loses transactions.
OVERLAP_DAYS = 7

# First sync of a new connection: enough history for budgets and dashboards to
# have something to say immediately.
INITIAL_HISTORY_DAYS = 90

# Name fragments that reliably indicate an account type. Only used to
# pre-fill a guess on first discovery; the type is editable in settings.
TYPE_HINTS = [
    ("credit", AccountType.CREDIT_CARD),
    ("card", AccountType.CREDIT_CARD),
    ("visa", AccountType.CREDIT_CARD),
    ("mastercard", AccountType.CREDIT_CARD),
    ("checking", AccountType.CHECKING),
    ("money market", AccountType.MONEY_MARKET),
    ("savings", AccountType.SAVINGS),
    ("mortgage", AccountType.MORTGAGE),
    ("student", AccountType.STUDENT_LOAN),
    ("auto loan", AccountType.AUTO_LOAN),
    ("loan", AccountType.STUDENT_LOAN),
    ("401", AccountType.RETIREMENT),
    ("ira", AccountType.RETIREMENT),
    ("roth", AccountType.RETIREMENT),
    ("brokerage", AccountType.INVESTMENT),
    ("invest", AccountType.INVESTMENT),
]


@dataclass
class SyncSummary:
    accounts_synced: int = 0
    transactions_created: int = 0
    transactions_updated: int = 0
    errors: list[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


def guess_account_type(name: str) -> str:
    haystack = (name or "").casefold()

    for fragment, account_type in TYPE_HINTS:
        if fragment in haystack:
            return account_type

    return AccountType.OTHER


def normalise_balance(raw: Decimal | None, account: Account) -> Decimal | None:
    """Convert a provider balance into the household's net-worth convention.

    Assets pass through. Liabilities are negated, because providers almost
    always report a debt as a positive "amount owed" — and negating rather
    than taking -abs() means an overpaid credit card still reads correctly as
    a positive balance. Institutions that report debts already-negative are
    handled by clearing `debt_reported_positive` on the account.
    """
    if raw is None:
        return None

    if account.account_type in LIABILITY_TYPES and account.debt_reported_positive:
        return -raw

    return raw


def next_fingerprint(account_id, posted_on, amount, description):
    """A free fingerprint for a new row, stepping past genuine duplicates.

    Two identical transactions on the same day are legitimate, so rather than
    rejecting the second we walk the sequence until we find an unused slot.
    """
    for sequence in range(100):
        candidate = build_fingerprint(
            account_id=account_id,
            posted_on=posted_on,
            amount=amount,
            description=description,
            sequence=sequence,
        )

        if not Transaction.objects.filter(
            account_id=account_id, fingerprint=candidate
        ).exists():
            return candidate

    # 100 identical transactions on one day on one account is not a real
    # scenario; treat it as a bug rather than looping forever.
    raise ProviderError(
        f"Could not find a free fingerprint for account {account_id} on {posted_on}."
    )


def default_since(connection: AccountConnection) -> date:
    if connection.last_synced_at is None:
        return timezone.localdate() - timedelta(days=INITIAL_HISTORY_DAYS)

    return timezone.localdate(connection.last_synced_at) - timedelta(days=OVERLAP_DAYS)


def upsert_account(connection: AccountConnection, payload) -> Account:
    account = Account.objects.filter(
        connection=connection, provider_account_id=payload.provider_account_id
    ).first()

    if account is None:
        account = Account(
            connection=connection,
            institution=connection.institution,
            provider_account_id=payload.provider_account_id,
            name=payload.name,
            account_type=guess_account_type(payload.name),
        )

    # The household's own name for an account wins over the provider's, so a
    # rename in settings is not undone by the next sync.
    account.official_name = payload.official_name or account.official_name
    account.currency = payload.currency or account.currency

    balance = normalise_balance(payload.raw_balance, account)

    if balance is not None:
        account.current_balance = balance
        account.available_balance = normalise_balance(
            payload.raw_available_balance, account
        )
        account.balance_as_of = timezone.now()

    account.save()

    if balance is not None:
        record_balance_snapshot(
            account,
            as_of=payload.balance_as_of or timezone.localdate(),
            current=balance,
            available=account.available_balance,
        )

    return account


def record_balance_snapshot(account, *, as_of, current, available=None, source=None):
    """One reading per account per day; a re-run overwrites rather than stacks."""
    AccountBalanceSnapshot.objects.update_or_create(
        account=account,
        as_of=as_of,
        defaults={
            "current": current,
            "available": available,
            "credit_limit": account.credit_limit,
            "source": source or BalanceSource.PROVIDER,
        },
    )


def upsert_transaction(account: Account, payload) -> str:
    """Insert or refresh one transaction. Returns 'created' or 'updated'."""
    existing = Transaction.objects.filter(
        account=account, provider_txn_id=payload.provider_txn_id
    ).first()

    if existing is not None:
        # A pending transaction settles with a different amount and date, so
        # these have to be refreshed rather than treated as immutable.
        changed_fields = []

        for attribute, value in [
            ("posted_on", payload.posted_on),
            ("amount", payload.amount),
            ("description_raw", payload.description),
            ("is_pending", payload.is_pending),
        ]:
            if getattr(existing, attribute) != value:
                setattr(existing, attribute, value)
                changed_fields.append(attribute)

        if changed_fields:
            existing.save(update_fields=changed_fields + ["updated_at"])
            return "updated"

        return "unchanged"

    Transaction.objects.create(
        account=account,
        provider_txn_id=payload.provider_txn_id,
        fingerprint=next_fingerprint(
            account.id, payload.posted_on, payload.amount, payload.description
        ),
        posted_on=payload.posted_on,
        amount=payload.amount,
        description_raw=payload.description,
        merchant=payload.merchant,
        is_pending=payload.is_pending,
        source=TransactionSource.PROVIDER,
    )

    return "created"


def sync_connection(
    connection: AccountConnection,
    *,
    since: date | None = None,
    trigger: str = SyncTrigger.SCHEDULE,
) -> SyncRun:
    """Pull one connection. Never raises; failures land on the run and the connection."""
    run = SyncRun.objects.create(connection=connection, trigger=trigger)

    if not connection.is_syncable:
        run.finish(
            SyncStatus.FAILED,
            error=f"Connection is {connection.get_status_display().lower()} or has no stored credential.",
        )
        return run

    since = since or default_since(connection)

    try:
        result = get_adapter(connection.provider).fetch(
            access_secret=connection.access_secret, since=since
        )
    except ProviderAuthError as exc:
        connection.mark_failed(exc, needs_reauth=True)
        run.finish(SyncStatus.FAILED, error=str(exc))
        return run
    except ProviderError as exc:
        connection.mark_failed(exc)
        run.finish(SyncStatus.FAILED, error=str(exc))
        return run

    summary = SyncSummary(errors=list(result.errors))

    for account_payload in result.accounts:
        try:
            # Per-account atomicity: one bad account must not roll back the
            # accounts that synced cleanly before it.
            with db_transaction.atomic():
                account = upsert_account(connection, account_payload)

                for txn_payload in result.transactions.get(
                    account_payload.provider_account_id, []
                ):
                    outcome = upsert_transaction(account, txn_payload)

                    if outcome == "created":
                        summary.transactions_created += 1
                    elif outcome == "updated":
                        summary.transactions_updated += 1

                summary.accounts_synced += 1
        except Exception as exc:  # noqa: BLE001 — one account must not sink the run
            logger.exception("Failed syncing account %s", account_payload.provider_account_id)
            summary.errors.append(f"{account_payload.name}: {exc}")

    run.accounts_synced = summary.accounts_synced
    run.transactions_created = summary.transactions_created
    run.transactions_updated = summary.transactions_updated

    if summary.errors:
        connection.mark_failed("; ".join(summary.errors)[:2000])
        run.finish(SyncStatus.PARTIAL, error="; ".join(summary.errors))
    else:
        connection.mark_synced()
        run.finish(SyncStatus.SUCCESS)

    return run


def sync_all_connections(*, since=None, trigger=SyncTrigger.SCHEDULE, high_frequency_only=False):
    """Sync every active connection. Returns the runs, in order."""
    connections = AccountConnection.objects.filter(
        status__in=["active", "error"]
    ).select_related("institution")

    if high_frequency_only:
        # Loans, mortgages, and policies move monthly at most — there is no
        # point asking for them every hour, and SimpleFIN caps daily requests.
        connections = connections.filter(
            accounts__account_type__in=[
                AccountType.CHECKING,
                AccountType.SAVINGS,
                AccountType.MONEY_MARKET,
                AccountType.CREDIT_CARD,
            ]
        ).distinct()

    return [
        sync_connection(connection, since=since, trigger=trigger)
        for connection in connections
    ]
