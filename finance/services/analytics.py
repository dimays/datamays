"""Aggregations behind the three dashboards.

Returns plain dicts of labels and series, ready to hand to a chart, so the
views stay thin and the arithmetic is testable without rendering anything.

The rules from the rest of the app hold here too: transfers never count as
spend or income, and balances come from dated snapshots rather than being
reconstructed from transactions — which is impossible for the accounts that
only ever report a balance.
"""

from collections import OrderedDict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import TruncDay, TruncMonth, TruncWeek
from django.utils import timezone

from ..models import (
    LIABILITY_TYPES,
    RETAINED_KINDS,
    Account,
    AccountBalanceSnapshot,
    Category,
    CategoryKind,
    Paycheck,
    Transaction,
)

GRAINS = {
    "daily": (TruncDay, "%-d %b"),
    "weekly": (TruncWeek, "%-d %b"),
    "monthly": (TruncMonth, "%b %Y"),
}


def _base_spend_queryset(start, end, account_ids=None):
    queryset = Transaction.objects.filter(
        posted_on__gte=start,
        posted_on__lte=end,
        is_transfer=False,
        amount__lt=0,
        category__kind=CategoryKind.EXPENSE,
    )

    if account_ids:
        queryset = queryset.filter(account_id__in=account_ids)

    return queryset


def spend_over_time(start, end, *, grain="monthly", account_ids=None):
    """Total outflow per period, as positive numbers."""
    trunc, label_format = GRAINS.get(grain, GRAINS["monthly"])

    rows = (
        _base_spend_queryset(start, end, account_ids)
        .annotate(bucket=trunc("posted_on"))
        .values("bucket")
        .annotate(total=Sum("amount"))
        .order_by("bucket")
    )

    return {
        "labels": [row["bucket"].strftime(label_format) for row in rows],
        "values": [float(-row["total"]) for row in rows],
    }


def spend_by_category(start, end, *, account_ids=None, limit=10):
    """Spend grouped by top-level category, largest first.

    Rolled up to the parent because a flat list of forty leaves is a table,
    not a chart — the leaf detail lives in the activity list.
    """
    rows = (
        _base_spend_queryset(start, end, account_ids)
        .values("category__id", "category__name", "category__parent__name")
        .annotate(total=Sum("amount"))
    )

    grouped = {}

    for row in rows:
        name = row["category__parent__name"] or row["category__name"]
        grouped[name] = grouped.get(name, Decimal("0")) + -row["total"]

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
    end = end or timezone.localdate()
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


def default_range(months=12):
    end = timezone.localdate()
    start = (end.replace(day=1) - timedelta(days=30 * months)).replace(day=1)
    return start, end
