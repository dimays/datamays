from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "The daily chain: sync everything including slow-moving accounts, "
        "categorize, snapshot balances, roll up budgets, and send due reports."
    )

    STEPS = [
        # No high-frequency filter here: this is the run that picks up loans,
        # the mortgage, and anything the hourly chain skips.
        ("sync_accounts", {}),
        ("categorize_transactions", {}),
        ("snapshot_balances", {}),
        ("rollup_budgets", {}),
        ("send_reports", {}),
    ]

    def handle(self, *args, **options):
        failures = []

        for name, kwargs in self.STEPS:
            try:
                call_command(name, verbosity=options["verbosity"], **kwargs)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{name}: {exc}")
                self.stderr.write(self.style.ERROR(f"{name} failed: {exc}"))

        if failures:
            raise SystemExit(1)
