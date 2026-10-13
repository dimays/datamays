import logging

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from finance.dates import household_timezone

logger = logging.getLogger(__name__)

# New transactions are fetched every third hour, not every hour. SimpleFIN
# allows roughly 24 requests a day; hourly plus the daily chain made about
# 25, and each retry after a failed fetch adds one more. Every third hour is
# 8 a day (9 with the daily chain, 18 at most with retries), and the banks
# feed SimpleFIN about once a day anyway. Decided with David, 2026-10-12.
SYNC_EVERY_HOURS = 3


def sync_due(now=None):
    """Whether this hour's run fetches new transactions: on household hours
    0, 3, 6, … so the schedule doesn't drift with the scheduler's minute."""
    now = now or timezone.now()
    return now.astimezone(household_timezone()).hour % SYNC_EVERY_HOURS == 0


class Command(BaseCommand):
    help = (
        "The hourly chain: sync day-to-day accounts (every third hour), "
        "categorize what arrived, roll up budgets, then evaluate alerts. "
        "Wired to Heroku Scheduler."
    )

    # Order matters: alerts must see freshly rolled-up budgets, and budgets
    # must see freshly categorized transactions.
    STEPS = [
        ("sync_accounts", {"high_frequency_only": True}),
        ("categorize_transactions", {}),
        ("rollup_budgets", {}),
        ("send_alerts", {}),
    ]

    def handle(self, *args, **options):
        failures = []
        steps = self.STEPS if sync_due() else [step for step in self.STEPS if step[0] != "sync_accounts"]

        for name, kwargs in steps:
            try:
                call_command(name, verbosity=options["verbosity"], **kwargs)
            except Exception as exc:  # noqa: BLE001
                # A failing sync should not stop budgets being rolled up from
                # the data already present, so each step is isolated.
                failures.append(f"{name}: {exc}")
                self.stderr.write(self.style.ERROR(f"{name} failed: {exc}"))
                # Logged, so Sentry reports it; stderr reaches only the logs.
                logger.exception("Scheduled step %s failed", name)

        if failures:
            # Non-zero exit so a broken chain is visible in Heroku's logs
            # rather than passing silently.
            raise SystemExit(1)
