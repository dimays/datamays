"""Evaluating alerts and sending them.

Two things matter more than the arithmetic here.

**Cooldowns.** The hourly run re-evaluates every alert, so without a cooldown a
breached threshold would email once an hour until it stopped being breached.
An alert people mute is worse than no alert.

**Honesty about staleness.** An alert derived from a balance that has not
refreshed in days is a guess. Those are still sent — silence would be worse —
but they say so.
"""

import logging
from datetime import datetime, time
from decimal import Decimal

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from ..dates import household_timezone, household_today
from ..models import UNIT_HOURS, Alert, AlertEvent, AlertKind, BudgetPeriod, Comparison, ThresholdUnit
from ..periods import elapsed_fraction

logger = logging.getLogger(__name__)


def last_activity_at(account):
    """When this account most recently reported anything, or None if never.

    One definition serves both halves of "a source not syncing": an automated
    connection's own last_synced_at is precise to the minute, while a manual
    account (the mortgage, the life policy) has no connection to ask, so this
    falls back to its newest balance snapshot — written both by sync and by
    CSV import (services.sync.record_balance_snapshot,
    services.importer._commit_balance), which makes it the one signal common
    to every account regardless of how it's kept current.
    """
    if account.connection_id and account.connection.last_synced_at:
        return account.connection.last_synced_at

    snapshot = account.balance_snapshots.order_by("-as_of").first()

    if snapshot is None:
        return None

    return timezone.make_aware(
        datetime.combine(snapshot.as_of, time.min), household_timezone()
    )


def staleness_value(alert):
    """Age since last activity, expressed in the alert's own unit.

    Returning it pre-converted (rather than always in hours) is what lets
    is_breached() stay a single generic `value > alert.threshold` — no
    staleness-specific comparison logic needed anywhere else.
    """
    last_activity = last_activity_at(alert.account)

    if last_activity is None:
        # A brand-new account has no baseline to measure staleness against.
        # It gets one grace cycle rather than alerting immediately.
        return None

    age_hours = (timezone.now() - last_activity).total_seconds() / 3600
    unit_hours = UNIT_HOURS[alert.threshold_unit or ThresholdUnit.HOURS]

    return Decimal(str(round(age_hours / unit_hours, 4)))


def observed_value(alert):
    """The number this alert watches, or None when it cannot be read."""
    if alert.kind == AlertKind.ACCOUNT_BALANCE:
        if alert.account is None or alert.account.current_balance is None:
            return None

        # Compared as a magnitude so "card above $2,000" means what a person
        # means, rather than depending on the storage sign.
        return (
            abs(alert.account.current_balance)
            if alert.account.is_liability
            else alert.account.current_balance
        )

    if alert.kind == AlertKind.SOURCE_STALE:
        return staleness_value(alert)

    period = current_period_for(alert.budget)

    if period is None:
        return None

    if alert.kind == AlertKind.BUDGET_AMOUNT:
        return period.actual_amount

    if not period.target_amount:
        return None

    return (period.actual_amount / period.target_amount) * 100


def current_period_for(budget):
    if budget is None:
        return None

    today = household_today()

    return BudgetPeriod.objects.filter(
        budget=budget, period_start__lte=today, period_end__gte=today
    ).first()


def is_breached(alert, value):
    if value is None:
        return False

    if alert.comparison == Comparison.ABOVE:
        return value > alert.threshold

    return value < alert.threshold


def is_in_cooldown(alert, now=None):
    if alert.last_triggered_at is None:
        return False

    now = now or timezone.now()
    elapsed_hours = (now - alert.last_triggered_at).total_seconds() / 3600

    return elapsed_hours < alert.cooldown_hours


def period_gate_passed(alert):
    """Whether a budget alert's "only after N% of the period" gate is met.

    This is what makes "80% of the grocery budget before the 15th" expressible:
    the same spend is unremarkable late in a period and worth knowing about
    early.
    """
    if alert.only_after_period_fraction is None:
        return True

    period = current_period_for(alert.budget)

    if period is None:
        return False

    elapsed = elapsed_fraction(
        period.period_start, period.period_end, household_today()
    )

    return elapsed >= alert.only_after_period_fraction


def build_message(alert, value):
    if alert.kind == AlertKind.ACCOUNT_BALANCE:
        direction = "risen above" if alert.comparison == Comparison.ABOVE else "fallen below"
        message = (
            f"{alert.account.name} has {direction} ${alert.threshold:,.2f}. "
            f"It is currently ${value:,.2f}."
        )

        if _is_stale(alert.account):
            message += (
                "\n\nNote: this balance has not refreshed recently, so it may "
                "be out of date."
            )

        return message

    if alert.kind == AlertKind.SOURCE_STALE:
        return _staleness_message(alert)

    period = current_period_for(alert.budget)

    if alert.kind == AlertKind.BUDGET_PERCENT:
        headline = (
            f"{alert.budget.name} is at {value:.0f}% of its "
            f"${period.target_amount:,.0f} target."
        )
    else:
        headline = (
            f"{alert.budget.name} has reached ${value:,.2f} "
            f"of its ${period.target_amount:,.0f} target."
        )

    pace = period.pace_difference()
    pacing = (
        f"That is ${pace:,.0f} ahead of an even pace"
        if pace > 0
        else f"That is ${abs(pace):,.0f} behind an even pace"
    )

    return (
        f"{headline}\n\n{pacing}, with the period running to "
        f"{period.period_end:%-d %B}."
    )


def _staleness_message(alert):
    account = alert.account
    last_activity = last_activity_at(account)
    unit_label = alert.get_threshold_unit_display().lower()

    if last_activity is None:
        return (
            f"{account.name} has no recorded sync or import yet — nothing to "
            f"compare the {unit_label} threshold against."
        )

    # A connected account is meant to sync on its own; a manual one is meant
    # to be refreshed by hand. The wording should say which kind of attention
    # is actually needed.
    verb = "synced" if account.connection_id else "been updated"
    action = (
        "Check the connection in Settings."
        if account.connection_id
        else "Import a fresh statement from Settings → Imports."
    )

    return (
        f"{account.name} hasn't {verb} in over {alert.threshold:.0f} {unit_label} "
        f"(last activity {timezone.localtime(last_activity):%-d %B %Y}). {action}"
    )


def _is_stale(account, days=3):
    if account.is_manual or account.balance_as_of is None:
        return False

    return (timezone.now() - account.balance_as_of).days >= days


def evaluate_alerts(*, send=True, now=None):
    """Check every active alert. Returns the events that fired."""
    now = now or timezone.now()
    fired = []

    alerts = Alert.objects.filter(is_active=True).select_related(
        "account", "account__connection", "budget", "user"
    )

    for alert in alerts:
        value = observed_value(alert)

        if not is_breached(alert, value):
            continue

        if not period_gate_passed(alert):
            continue

        if is_in_cooldown(alert, now):
            continue

        event = AlertEvent.objects.create(
            alert=alert,
            # Quantised, never routed through float — see models.base.
            observed_value=Decimal(value).quantize(Decimal("0.01")),
            message=build_message(alert, value),
        )

        if send:
            deliver(event)

        alert.last_triggered_at = now
        alert.save(update_fields=["last_triggered_at", "updated_at"])

        fired.append(event)

    return fired


def deliver(event):
    """Email one alert. Delivery failures are recorded, never raised.

    A mail outage must not stop the remaining alerts from being evaluated.
    """
    recipient = event.alert.user.email

    if not recipient:
        event.delivery_error = "No email address on this account."
        event.save(update_fields=["delivery_error"])
        return False

    try:
        send_mail(
            subject=f"[Household Finance] {event.alert.name}",
            message=event.message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            fail_silently=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Could not deliver alert %s", event.alert_id)
        event.delivery_error = str(exc)[:500]
        event.save(update_fields=["delivery_error"])
        return False

    event.was_delivered = True
    event.save(update_fields=["was_delivered"])

    return True
