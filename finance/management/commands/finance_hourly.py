from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "The hourly chain: sync day-to-day accounts, categorise what arrived, "
        "roll up budgets, then evaluate alerts. Wired to Heroku Scheduler."
    )

    # Order matters: alerts must see freshly rolled-up budgets, and budgets
    # must see freshly categorised transactions.
    STEPS = [
        ("sync_accounts", {"high_frequency_only": True}),
        ("categorize_transactions", {}),
        ("rollup_budgets", {}),
        ("send_alerts", {}),
    ]

    def handle(self, *args, **options):
        failures = []

        for name, kwargs in self.STEPS:
            try:
                call_command(name, verbosity=options["verbosity"], **kwargs)
            except Exception as exc:  # noqa: BLE001
                # A failing sync should not stop budgets being rolled up from
                # the data already present, so each step is isolated.
                failures.append(f"{name}: {exc}")
                self.stderr.write(self.style.ERROR(f"{name} failed: {exc}"))

        if failures:
            # Non-zero exit so a broken chain is visible in Heroku's logs
            # rather than passing silently.
            raise SystemExit(1)
