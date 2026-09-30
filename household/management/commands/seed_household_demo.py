from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from household.services import demo


class Command(BaseCommand):
    help = (
        "Fill a LOCAL SQLite database with a fictional household for clicking "
        "around. Refuses to run against anything but SQLite."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Wipe the local database first, then seed from scratch.",
        )

    def handle(self, *args, **options):
        try:
            demo.ensure_local_database()
        except demo.NotALocalDatabase as exc:
            raise CommandError(str(exc))

        if options["reset"]:
            call_command("flush", interactive=False, verbosity=0)
        elif demo.is_seeded():
            raise CommandError("Already seeded. Pass --reset to start over.")

        summary = demo.seed()

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {summary['accounts']} accounts, "
                f"{summary['transactions']} transactions, "
                f"{summary['budgets']} budgets, and "
                f"{summary['chores']} chores."
            )
        )
        self.stdout.write(
            f"Sign in as {' or '.join(summary['members'])} with the password "
            "in household/services/demo.py; get a second-factor code with "
            "`manage.py demo_totp_code <username>`."
        )
