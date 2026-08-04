from django.core.management.base import BaseCommand

from finance.services.alerts import evaluate_alerts


class Command(BaseCommand):
    help = "Evaluate active alerts and email any that have newly breached."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Evaluate and record events without sending email.",
        )

    def handle(self, *args, **options):
        fired = evaluate_alerts(send=not options["dry_run"])

        if options["verbosity"]:
            if not fired:
                self.stdout.write("No alerts fired.")
            for event in fired:
                self.stdout.write(self.style.WARNING(f"{event.alert.name}: {event.message.splitlines()[0]}"))
