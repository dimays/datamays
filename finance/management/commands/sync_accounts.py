from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from finance.models import AccountConnection, SyncStatus, SyncTrigger
from finance.services.sync import sync_all_connections, sync_connection


class Command(BaseCommand):
    help = (
        "Pull accounts, balances, and transactions from connected providers. "
        "Safe to re-run: every write is an upsert on a stable identity."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--connection",
            type=int,
            help="Sync a single connection by ID instead of all of them.",
        )
        parser.add_argument(
            "--since",
            help="Fetch from this date (YYYY-MM-DD) instead of the usual window.",
        )
        parser.add_argument(
            "--high-frequency-only",
            action="store_true",
            help="Only connections holding day-to-day accounts. Used by the hourly run.",
        )
        parser.add_argument(
            "--manual",
            action="store_true",
            help="Record the run as manually triggered rather than scheduled.",
        )

    def handle(self, *args, **options):
        since = self._parse_since(options.get("since"))
        trigger = SyncTrigger.MANUAL if options["manual"] else SyncTrigger.SCHEDULE

        if options.get("connection"):
            try:
                connection = AccountConnection.objects.get(pk=options["connection"])
            except AccountConnection.DoesNotExist:
                raise CommandError(f"No connection with ID {options['connection']}.")

            runs = [sync_connection(connection, since=since, trigger=trigger)]
        else:
            runs = sync_all_connections(
                since=since,
                trigger=trigger,
                high_frequency_only=options["high_frequency_only"],
            )

        self._report(runs)

    def _parse_since(self, value):
        if not value:
            return None

        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            raise CommandError("--since must be a date in YYYY-MM-DD form.")

    def _report(self, runs):
        if not runs:
            self.stdout.write("No connections to sync.")
            return

        failed = 0

        for run in runs:
            line = (
                f"{run.connection}: {run.status} — "
                f"{run.accounts_synced} accounts, "
                f"{run.transactions_created} new, "
                f"{run.transactions_updated} updated"
            )

            if run.status == SyncStatus.SUCCESS:
                self.stdout.write(self.style.SUCCESS(line))
            else:
                failed += 1
                self.stderr.write(self.style.ERROR(f"{line}\n  {run.error_message}"))

        # Exit non-zero so a failing scheduled run is visible as a failure
        # rather than a quiet log line nobody reads.
        if failed:
            raise CommandError(f"{failed} of {len(runs)} connections failed.")
