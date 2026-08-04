from django.core.management.base import BaseCommand
from finance.dates import household_today
from finance.models import Account
from finance.services.sync import record_balance_snapshot


class Command(BaseCommand):
    help = (
        "Record today's balance for every account that has one. Sync already "
        "snapshots the accounts it touches; this catches manual accounts and "
        "any day a sync did not run, so the history charts stay continuous."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            help="Record against this date (YYYY-MM-DD) instead of today.",
        )

    def handle(self, *args, **options):
        as_of = household_today()

        if options.get("date"):
            from datetime import datetime

            from django.core.management.base import CommandError

            try:
                as_of = datetime.strptime(options["date"], "%Y-%m-%d").date()
            except ValueError:
                raise CommandError("--date must be YYYY-MM-DD.")

        recorded = 0

        for account in Account.objects.filter(is_active=True):
            if account.current_balance is None:
                continue

            record_balance_snapshot(
                account,
                as_of=as_of,
                current=account.current_balance,
                available=account.available_balance,
            )
            recorded += 1

        if options["verbosity"]:
            self.stdout.write(
                self.style.SUCCESS(f"Recorded {recorded} balances for {as_of}.")
            )
