"""Aggregations behind the three dashboards.

Returns plain dicts of labels and series, ready to hand to a chart, so the
views stay thin and the arithmetic is testable without rendering anything.

The rules from the rest of the app hold here too: transfers never count as
spend or income, and balances come from dated snapshots rather than being
reconstructed from transactions — which is impossible for the accounts that
only ever report a balance.
"""

import calendar
from collections import OrderedDict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.db.models.functions import TruncDay, TruncMonth, TruncWeek

from ..dates import household_today
from ..models import (
    LIABILITY_TYPES,
    RETAINED_KINDS,
    Account,
    AccountBalanceSnapshot,
    CategoryKind,
    Paycheck,
    Transaction,
)

GRAINS = {
    "daily": (TruncDay, "%-d %b"),
    "weekly": (TruncWeek, "%-d %b"),
    "monthly": (TruncMonth, "%b %Y"),
}


def spend_filter() -> Q:
    """What counts as spend, as a reusable Q rather than a bound queryset.

    Excludes income and transfers, but *keeps* transactions with no category
    yet. Requiring an expense category silently dropped everything the
    categoriser had not reached — and since the hourly chain isolates step
    failures, a broken categorise run would have made the dashboards
    under-report spend while looking perfectly healthy.

    A positive amount against an expense category counts too — a refund or a
    credit posted as its own transaction should net back against the outflow
    it corrects, not sit invisibly outside every spend total just because its
    sign differs from the purchase. This is deliberately narrower than "any
    positive amount, any category": an *uncategorised* positive transaction
    is far more likely to be income the classifier hasn't reached yet than a
    refund, so that bucket keeps the original amount__lt=0 requirement.
    Aggregates built on this Q floor a negative net (more refunded than
    spent) at zero rather than showing a category as having "spent" a
    negative amount — see spend_over_time / spend_by_category.

    Split out from spend_transactions() so the activity list can apply this
    exact definition (via TransactionListView's `spend=1`) without also being
    forced to supply a date range — a chart click already carries its own
    start/end, and re-deriving them here would risk the two drifting apart.
    """
    return Q(is_transfer=False) & (
        Q(category__kind=CategoryKind.EXPENSE)
        | Q(category__isnull=True, amount__lt=0)
    )


def spend_transactions(start, end, account_ids=None):
    """Transactions that count as spend in a window — the shared definition.

    Public rather than a module-private helper: clicking a bar in a chart
    built from this function should show precisely the rows that produced its
    number, not an approximation of them.
    """
    queryset = Transaction.objects.filter(
        spend_filter(), posted_on__gte=start, posted_on__lte=end
    )

    if account_ids:
        queryset = queryset.filter(account_id__in=account_ids)

    return queryset


def _bucket_end(bucket_start: date, grain: str) -> date:
    """The last day covered by a bucket, given its first day.

    Needed so a clicked chart bar can link to a transaction list filtered to
    exactly the days that fed it — Trunc*() gives back the bucket's start, not
    its span.
    """
    if grain == "daily":
        return bucket_start

    if grain == "weekly":
        # TruncWeek anchors to the Monday of the ISO week regardless of locale.
        return bucket_start + timedelta(days=6)

    last_day = calendar.monthrange(bucket_start.year, bucket_start.month)[1]
    return bucket_start.replace(day=last_day)


def spend_over_time(start, end, *, grain="monthly", account_ids=None):
    """Total outflow per period, as positive numbers."""
    trunc, label_format = GRAINS.get(grain, GRAINS["monthly"])

    rows = (
        spend_transactions(start, end, account_ids)
        .annotate(bucket=trunc("posted_on"))
        .values("bucket")
        .annotate(total=Sum("amount"))
        .order_by("bucket")
    )
    rows = list(rows)

    return {
        "labels": [row["bucket"].strftime(label_format) for row in rows],
        # Floored at 0: a bucket where refunds outweighed purchases nets to a
        # positive raw total (negated below), which would otherwise chart as
        # negative spend — a bar reading "spent -$40" is a rendering bug, not
        # a real answer to "how much did this period spend."
        "values": [max(0.0, float(-row["total"])) for row in rows],
        # Exact bounds per bucket, so a chart click can filter the activity
        # list to precisely what that bar represents.
        "bucket_starts": [row["bucket"].isoformat() for row in rows],
        "bucket_ends": [_bucket_end(row["bucket"], grain).isoformat() for row in rows],
    }


def spend_by_category(start, end, *, account_ids=None, limit=10):
    """Spend grouped by top-level category, largest first.

    Rolled up to the parent because a flat list of forty leaves is a table,
    not a chart — the leaf detail lives in the activity list.
    """
    rows = (
        spend_transactions(start, end, account_ids)
        .values("category__id", "category__name", "category__parent__name")
        .annotate(total=Sum("amount"))
    )

    grouped = {}

    for row in rows:
        # Surfaced as its own slice rather than hidden, so an unclassified
        # backlog is visible on the chart instead of quietly missing from it.
        name = (
            row["category__parent__name"]
            or row["category__name"]
            or "Not yet categorised"
        )
        grouped[name] = grouped.get(name, Decimal("0")) + -row["total"]

    # Floored per category, after rollup: a category refunded more than it
    # spent in the window nets negative here, which would read as the
    # category "making money" rather than what actually happened.
    grouped = {name: max(Decimal("0"), total) for name, total in grouped.items()}

    ranked = sorted(grouped.items(), key=lambda item: item[1], reverse=True)
    top = ranked[:limit]
    rest = ranked[limit:]

    if rest:
        top.append(("Everything else", sum(amount for _, amount in rest)))

    return {
        "labels": [name for name, _ in top],
        "values": [float(amount) for _, amount in top],
        "total": float(sum(amount for _, amount in ranked)),
    }


def budget_attainment_over_time(budget, periods=12):
    """Actual versus target for a budget's recent periods, oldest first."""
    rows = list(budget.budget_periods.order_by("-period_start")[:periods])
    rows.reverse()

    return {
        "labels": [row.period_start.strftime("%b %Y") for row in rows],
        "actual": [float(row.actual_amount) for row in rows],
        "target": [float(row.target_amount) for row in rows],
        # So a clicked bar can open the activity list scoped to that one
        # historical period rather than the budget's current one.
        "period_starts": [row.period_start.isoformat() for row in rows],
        "period_ends": [row.period_end.isoformat() for row in rows],
    }


def income_over_time(start, end, *, grain="monthly"):
    """Gross and net pay per period, plus what the gap is made of.

    Aggregators only ever see the deposit, so this reads from imported
    paychecks. Retirement and HSA are separated out because that money is
    still the household's — treating it as lost the way tax is would
    understate what they actually earn.
    """
    paychecks = (
        Paycheck.objects.filter(pay_date__gte=start, pay_date__lte=end)
        .prefetch_related("deductions")
        .order_by("pay_date")
    )

    buckets = OrderedDict()

    for paycheck in paychecks:
        key = paycheck.pay_date.replace(day=1)
        bucket = buckets.setdefault(
            key,
            {"gross": Decimal("0"), "net": Decimal("0"), "retained": Decimal("0"), "tax": Decimal("0"), "other": Decimal("0")},
        )

        bucket["gross"] += paycheck.gross
        bucket["net"] += paycheck.net

        for line in paycheck.deductions.all():
            if line.kind in RETAINED_KINDS:
                bucket["retained"] += line.amount
            elif "tax" in line.kind or line.kind == "fica":
                bucket["tax"] += line.amount
            else:
                bucket["other"] += line.amount

    return {
        "labels": [key.strftime("%b %Y") for key in buckets],
        "gross": [float(v["gross"]) for v in buckets.values()],
        "net": [float(v["net"]) for v in buckets.values()],
        "tax": [float(v["tax"]) for v in buckets.values()],
        "retained": [float(v["retained"]) for v in buckets.values()],
        "other": [float(v["other"]) for v in buckets.values()],
        "has_data": bool(buckets),
    }


def deposits_without_paychecks(start, end):
    """Income transactions with no matching paycheck record.

    Surfaced so the income dashboard can say "this is incomplete" rather than
    quietly under-reporting when a payslip has not been imported.
    """
    return (
        Transaction.objects.filter(
            posted_on__gte=start,
            posted_on__lte=end,
            amount__gt=0,
            is_transfer=False,
            category__kind=CategoryKind.INCOME,
            paycheck__isnull=True,
        )
        .select_related("account", "category")
        .order_by("-posted_on")
    )


def balance_history(account_ids=None, *, start=None, end=None, account_types=None):
    """Daily balance series per account, carried forward across quiet days.

    Snapshots only exist for days an account reported, so a mortgage that
    updates monthly would otherwise draw a chart of disconnected dots.
    """
    end = end or household_today()
    start = start or (end - timedelta(days=365))

    accounts = Account.objects.filter(is_active=True)

    if account_ids:
        accounts = accounts.filter(pk__in=account_ids)

    if account_types:
        accounts = accounts.filter(account_type__in=account_types)

    accounts = list(accounts)

    snapshots = AccountBalanceSnapshot.objects.filter(
        account__in=accounts, as_of__gte=start, as_of__lte=end
    ).order_by("as_of")

    by_account = {}

    for snapshot in snapshots:
        by_account.setdefault(snapshot.account_id, {})[snapshot.as_of] = snapshot.current

    # An account almost certainly had a balance before the window opened, so
    # seed each series from its most recent earlier snapshot. Without this the
    # chart starts at nothing and appears to plunge on day one.
    for account in accounts:
        opening = (
            AccountBalanceSnapshot.objects.filter(account=account, as_of__lt=start)
            .order_by("-as_of")
            .first()
        )

        if opening is not None:
            by_account.setdefault(account.pk, {}).setdefault(start, opening.current)

    labels = []
    cursor = start

    while cursor <= end:
        labels.append(cursor)
        cursor += timedelta(days=1)

    series = []

    for account in accounts:
        points = by_account.get(account.pk, {})

        if not points:
            continue

        values = []
        carried = None

        for day in labels:
            if day in points:
                carried = points[day]

            values.append(float(carried) if carried is not None else None)

        series.append(
            {
                "account": account,
                "label": account.name,
                "is_liability": account.account_type in LIABILITY_TYPES,
                "values": values,
            }
        )

    return {
        "labels": [day.strftime("%-d %b %Y") for day in labels],
        "series": series,
    }


def net_worth_history(*, start=None, end=None):
    """Total net worth per day, from the same carried-forward snapshots."""
    history = balance_history(
        start=start,
        end=end,
        account_ids=list(
            Account.objects.filter(
                is_active=True, include_in_net_worth=True
            ).values_list("pk", flat=True)
        ),
    )

    totals = []

    for index in range(len(history["labels"])):
        reported = [
            series["values"][index]
            for series in history["series"]
            if series["values"][index] is not None
        ]

        # None rather than zero on days nothing has reported yet: a zero would
        # draw a cliff down to the axis and read as the household being broke.
        totals.append(round(sum(reported), 2) if reported else None)

    return {"labels": history["labels"], "values": totals}


def net_worth_as_of(when: date) -> Decimal | None:
    """Net worth on a single day, from each account's latest snapshot at or
    before it.

    None rather than 0 when nothing has reported yet by that date — used by
    the QFR to tell "we had no data yet" apart from "net worth was zero", the
    same distinction net_worth_history draws for its chart.
    """
    total = None

    for account in Account.objects.filter(is_active=True, include_in_net_worth=True):
        snapshot = (
            account.balance_snapshots.filter(as_of__lte=when).order_by("-as_of").first()
        )

        if snapshot is None:
            continue

        total = (total or Decimal("0")) + snapshot.current

    return total


def default_range(months=12):
    end = household_today()
    start = (end.replace(day=1) - timedelta(days=30 * months)).replace(day=1)
    return start, end
