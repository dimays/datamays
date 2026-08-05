"""Re-point each account's cached balance at its newest snapshot.

A repair tool, not part of any scheduled chain. Every path that writes a
balance keeps the cache current on its own; this exists for the case where
one of them didn't — a bug since fixed, an interrupted import, a row edited
directly in the database.

Dry by default. It prints what it would change and writes nothing unless
--apply is passed, because it is the kind of command someone reaches for
while already unsure what state the data is in.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from finance.models import Account
from finance.services.sync import refresh_account_balance_from_snapshots


class Command(BaseCommand):
    help = (
        "Re-point each account's cached balance (Account.current_balance) at "
        "its newest AccountBalanceSnapshot. Prints proposed changes; pass "
        "--apply to write them."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually write the changes. Without this, nothing is saved.",
        )
        parser.add_argument(
            "--account",
            type=int,
            help="Limit to one account id.",
        )
        parser.add_argument(
            "--only-empty",
            action="store_true",
            help=(
                "Only touch accounts with no cached balance at all. The "
                "conservative choice: it fills gaps without ever overriding a "
                "figure some other path deliberately set."
            ),
        )

    def handle(self, *args, **options):
        accounts = Account.objects.filter(is_active=True)

        if options.get("account"):
            accounts = accounts.filter(pk=options["account"])

        if options.get("only_empty"):
            accounts = accounts.filter(current_balance__isnull=True)

        pending = []

        for account in accounts:
            latest = account.balance_snapshots.order_by("-as_of").first()

            if latest is None or account.current_balance == latest.current:
                continue

            pending.append((account, latest))

        if not pending:
            self.stdout.write(self.style.SUCCESS("Every cached balance is current."))
            return

        verb = "Updating" if options["apply"] else "Would update"
        self.stdout.write(f"{verb} {len(pending)} account(s):")

        for account, latest in pending:
            self.stdout.write(
                f"  {account.name}: {account.current_balance} → {latest.current} "
                f"(snapshot {latest.as_of}, {latest.source})"
            )

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING("\nDry run. Re-run with --apply to write.")
            )
            return

        with transaction.atomic():
            for account, _ in pending:
                refresh_account_balance_from_snapshots(account)

        self.stdout.write(self.style.SUCCESS(f"\nUpdated {len(pending)} account(s)."))
