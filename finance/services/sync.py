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
from django.utils.text import slugify

from ..dates import household_start_of_day, household_today, to_household_date
from ..models import (
    LIABILITY_TYPES,
    Account,
    AccountBalanceSnapshot,
    AccountConnection,
    AccountType,
    ConnectionStatus,
    BalanceSource,
    Institution,
    SyncRun,
    SyncStatus,
    SyncTrigger,
    Transaction,
    TransactionSource,
    build_fingerprint,
)
from ..providers.base import ProviderAuthError, ProviderError, redact
from ..providers.registry import get_adapter

logger = logging.getLogger(__name__)

# How far back to re-read on a routine sync. Institutions amend and back-date
# postings for days after the fact, so only ever asking for "since last sync"
# quietly loses transactions.
OVERLAP_DAYS = 7

# First sync of a new connection: enough history for budgets and dashboards to
# have something to say immediately.
#
# Kept a few days short of SimpleFIN's stated 90-day cap rather than equal to
# it. The adapter sends `since` as midnight UTC (test_the_since_date_is_sent
# _as_an_epoch_start_date) so the actual elapsed span to "now" always has a
# fractional day added on top of the nominal day count — and household_today()
# can already be a day behind UTC late in the evening in America/Chicago. A
# value of exactly 90 reliably tips over SimpleFIN's limit and gets the
# request capped, which then reports as a sync error and — because
# last_synced_at never advances on a failed run — repeats on every retry
# instead of self-correcting.
INITIAL_HISTORY_DAYS = 87

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
    # Genuine per-account failures — something didn't save. These are what
    # actually make a run PARTIAL and block the connection from being marked
    # synced.
    errors: list[str] = None
    # Provider-level notices attached to the request as a whole (SimpleFIN's
    # top-level `errors`), most often a date-range recommendation from a
    # specific institution rather than anything actually failing. Recorded
    # for visibility, but must not block last_synced_at from advancing —
    # institutions vary in what range they'll tolerate, so treating every
    # notice as a failure means some connection is always stuck re-requesting
    # the same window and re-triggering the same notice forever.
    provider_notices: list[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.provider_notices is None:
            self.provider_notices = []


def guess_account_type(name: str) -> str:
    haystack = (name or "").casefold()

    for fragment, account_type in TYPE_HINTS:
        if fragment in haystack:
            return account_type

    return AccountType.OTHER


def normalize_balance(raw: Decimal | None, account: Account) -> Decimal | None:
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
        return household_today() - timedelta(days=INITIAL_HISTORY_DAYS)

    return to_household_date(connection.last_synced_at) - timedelta(days=OVERLAP_DAYS)


def resolve_institution(connection: AccountConnection, payload) -> Institution:
    """Which Institution a newly-discovered account belongs to.

    Trusts the provider's own report of it (`payload.institution_name`) over
    the connection's institution, since one SimpleFIN access can span several
    real institutions — assuming they all match the connection's would
    silently mislabel every account after the first. `connection.institution`
    is only a fallback for the rare account that doesn't come with one.
    """
    name = (getattr(payload, "institution_name", "") or "").strip()

    if name:
        institution, _ = Institution.objects.get_or_create(
            name=name,
            defaults={"slug": slugify(name)[:140], "provider": connection.provider},
        )
        return institution

    if connection.institution_id:
        return connection.institution

    raise ProviderError(
        f"{connection.get_provider_display()} did not report an institution "
        f"for account {payload.provider_account_id!r}, and this connection "
        "has no fallback institution set."
    )


def upsert_account(connection: AccountConnection, payload) -> Account:
    account = Account.objects.filter(
        connection=connection, provider_account_id=payload.provider_account_id
    ).first()

    if account is None:
        account = Account(
            connection=connection,
            institution=resolve_institution(connection, payload),
            provider_account_id=payload.provider_account_id,
            name=payload.name,
            account_type=guess_account_type(payload.name),
        )

    # The household's own name for an account wins over the provider's, so a
    # rename in settings is not undone by the next sync.
    account.official_name = payload.official_name or account.official_name
    account.currency = payload.currency or account.currency

    balance = normalize_balance(payload.raw_balance, account)

    if balance is not None:
        account.current_balance = balance
        account.available_balance = normalize_balance(
            payload.raw_available_balance, account
        )
        account.balance_as_of = timezone.now()

    account.save()

    if balance is not None:
        # Dated today, not at the provider's own balance_as_of.
        #
        # A provider balance is the current balance until the provider says
        # otherwise — an institution that last updated three days ago is still
        # telling us what the account holds right now. Dating the snapshot by
        # the provider's timestamp made the newest snapshot older than the
        # value cached on the account, so a manual reading entered today
        # outranked a sync that ran afterwards: the Charts tab showed the
        # manual figure while the homepage showed the provider's.
        #
        # Today's date keeps "newest snapshot" and Account.current_balance in
        # agreement, which is what makes a sync overwrite a manual entry
        # immediately rather than at the next daily snapshot_balances run.
        record_balance_snapshot(
            account,
            as_of=household_today(),
            current=balance,
            available=account.available_balance,
        )

    return account


def record_balance_snapshot(account, *, as_of, current, available=None, source=None):
    """One reading per account per day; a re-run overwrites rather than stacks.

    Writes history only. `Account.current_balance` is a separate, denormalized
    cache of the latest reading — see refresh_account_balance_from_snapshots()
    for why both exist and when to update the second one.
    """
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


def refresh_account_balance_from_snapshots(account) -> bool:
    """Point an account's cached balance at its newest snapshot.

    Two places hold a balance, on purpose:

    - `AccountBalanceSnapshot` is the history. Every balance chart is built
      from it, because summing transactions cannot work for an account that
      only ever reports a balance.
    - `Account.current_balance` caches the latest reading. The homepage, the
      account list and every net worth total read it, rather than running a
      per-account "newest snapshot" query on each page load.

    A provider sync writes both. CSV balance import wrote only the snapshot,
    so an imported balance appeared on the Charts tab and nowhere else —
    which is exactly the bug this function exists to close.

    Reads the newest snapshot rather than trusting the caller's row, so a
    file containing history (or rows out of order) still leaves the cache
    pointing at the most recent reading rather than the last one parsed.

    Returns whether anything was written.
    """
    latest = account.balance_snapshots.order_by("-as_of").first()

    if latest is None:
        return False

    account.current_balance = latest.current
    account.available_balance = latest.available
    account.balance_as_of = household_start_of_day(latest.as_of)
    account.save(
        update_fields=[
            "current_balance",
            "available_balance",
            "balance_as_of",
            "updated_at",
        ]
    )

    return True


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

    summary = SyncSummary(provider_notices=list(result.errors))

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
            summary.errors.append(f"{account_payload.name}: {redact(exc)}")

    run.accounts_synced = summary.accounts_synced
    run.transactions_created = summary.transactions_created
    run.transactions_updated = summary.transactions_updated

    if summary.errors:
        connection.mark_failed("; ".join(summary.errors)[:2000])
        run.finish(SyncStatus.PARTIAL, error="; ".join(summary.errors))
    elif summary.provider_notices:
        # The fetch still returned complete data for every account — this is
        # SimpleFIN remarking on the request, not reporting that anything
        # failed — so the connection is genuinely synced. The notice is kept
        # on this run for visibility without blocking last_synced_at.
        connection.mark_synced()
        run.finish(SyncStatus.SUCCESS, error="; ".join(summary.provider_notices)[:2000])
    else:
        connection.mark_synced()
        run.finish(SyncStatus.SUCCESS)

    return run


def sync_all_connections(*, since=None, trigger=SyncTrigger.SCHEDULE, high_frequency_only=False):
    """Sync every active connection. Returns the runs, in order."""
    connections = AccountConnection.objects.filter(
        status__in=[ConnectionStatus.ACTIVE, ConnectionStatus.ERROR]
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
