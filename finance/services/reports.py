"""Weekly and monthly email summaries.

Sections are chosen per report, so one person can get a full picture and the
other just the budgets. Rendered as plain text: these arrive on phones, and a
summary that reads cleanly in a notification preview beats one that needs
images loaded to make sense.
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from ..models import (
    Account,
    BudgetPeriod,
    ReportCadence,
    ScheduledReport,
    Transaction,
)
from .analytics import spend_by_category

logger = logging.getLogger(__name__)

SECTION_CHOICES = [
    ("balances", "Account balances"),
    ("budgets", "Budget attainment"),
    ("spend", "Spend by category"),
    ("transactions", "Largest transactions"),
    ("review", "Transactions needing review"),
]

DEFAULT_SECTIONS = ["balances", "budgets", "spend"]


def window_for(report, on_date=None):
    on_date = on_date or timezone.localdate()

    if report.cadence == ReportCadence.WEEKLY:
        return on_date - timedelta(days=7), on_date

    return on_date - timedelta(days=30), on_date


def is_due(report, on_date=None, now=None):
    """Whether this report should go out today.

    Guards on both the calendar day and the last send, so a second run on the
    same day — a retry, a manual invocation — does not send twice.
    """
    if not report.is_active:
        return False

    on_date = on_date or timezone.localdate()
    now = now or timezone.now()

    if report.cadence == ReportCadence.WEEKLY:
        # isoweekday: Monday is 1, matching send_day.
        if on_date.isoweekday() != report.send_day:
            return False
    elif on_date.day != report.send_day:
        return False

    if report.last_sent_at is None:
        return True

    return timezone.localtime(report.last_sent_at).date() < on_date


def _accounts_for(report):
    accounts = Account.objects.filter(is_active=True).select_related("institution")

    if report.account_ids:
        accounts = accounts.filter(pk__in=report.account_ids)

    return accounts


def build_sections(report, start, end):
    chosen = report.sections or DEFAULT_SECTIONS
    blocks = []

    if "balances" in chosen:
        accounts = list(_accounts_for(report))
        lines = [
            f"  {account.name}: ${account.display_balance:,.2f}"
            for account in accounts
            if account.display_balance is not None
        ]
        net_worth = sum(
            (a.current_balance or Decimal("0") for a in accounts if a.include_in_net_worth),
            Decimal("0"),
        )
        lines.append(f"  ---\n  Net worth: ${net_worth:,.2f}")
        blocks.append(("Balances", "\n".join(lines)))

    if "budgets" in chosen:
        periods = BudgetPeriod.objects.filter(
            budget__is_active=True, period_start__lte=end, period_end__gte=end
        ).select_related("budget")

        if report.budget_ids:
            periods = periods.filter(budget_id__in=report.budget_ids)

        lines = []

        for period in periods:
            state = "OVER" if period.is_over else "ok"
            lines.append(
                f"  {period.budget.name}: ${period.actual_amount:,.0f} of "
                f"${period.target_amount:,.0f} ({state})"
            )

        blocks.append(("Budgets", "\n".join(lines) or "  No active budgets."))

    if "spend" in chosen:
        breakdown = spend_by_category(start, end, account_ids=report.account_ids or None, limit=6)
        lines = [
            f"  {label}: ${value:,.0f}"
            for label, value in zip(breakdown["labels"], breakdown["values"])
        ]
        lines.append(f"  ---\n  Total: ${breakdown['total']:,.0f}")
        blocks.append(("Spend", "\n".join(lines)))

    if "transactions" in chosen:
        largest = (
            Transaction.objects.filter(
                posted_on__gte=start, posted_on__lte=end, is_transfer=False, amount__lt=0
            )
            .select_related("account")
            .order_by("amount")[:8]
        )
        lines = [
            f"  {t.posted_on:%-d %b}  ${t.display_amount:,.2f}  {t.description_raw[:44]}"
            for t in largest
        ]
        blocks.append(("Largest transactions", "\n".join(lines) or "  None."))

    if "review" in chosen:
        count = Transaction.objects.filter(needs_review=True).count()
        blocks.append(
            (
                "Needs review",
                f"  {count} transaction{'s' if count != 1 else ''} waiting to be categorised."
                if count
                else "  Nothing waiting.",
            )
        )

    return blocks


def render_report(report, start, end):
    blocks = build_sections(report, start, end)

    body = [
        f"Household Finance — {report.get_cadence_display().lower()} summary",
        f"{start:%-d %B} to {end:%-d %B %Y}",
        "",
    ]

    for title, content in blocks:
        body.extend([title.upper(), content, ""])

    body.append("Sent by datamays.com/finance")

    return "\n".join(body)


def send_report(report, on_date=None):
    start, end = window_for(report, on_date)
    recipient = report.user.email

    if not recipient:
        logger.warning("Report %s has no recipient address", report.pk)
        return False

    try:
        send_mail(
            subject=f"[Household Finance] {report.name}",
            message=render_report(report, start, end),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            fail_silently=False,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Could not send report %s", report.pk)
        return False

    report.last_sent_at = timezone.now()
    report.save(update_fields=["last_sent_at", "updated_at"])

    return True


def send_due_reports(on_date=None, *, cadence=None):
    reports = ScheduledReport.objects.filter(is_active=True).select_related("user")

    if cadence:
        reports = reports.filter(cadence=cadence)

    return [report for report in reports if is_due(report, on_date) and send_report(report, on_date)]
