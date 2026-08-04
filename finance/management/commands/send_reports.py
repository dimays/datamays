from django.core.management.base import BaseCommand

from finance.models import ReportCadence
from finance.services.reports import send_due_reports


class Command(BaseCommand):
    help = "Send any scheduled reports that are due today."

    def add_arguments(self, parser):
        parser.add_argument(
            "--cadence",
            choices=[value for value, _ in ReportCadence.choices],
            help="Only consider reports of this cadence.",
        )

    def handle(self, *args, **options):
        sent = send_due_reports(cadence=options.get("cadence"))

        if options["verbosity"]:
            self.stdout.write(
                self.style.SUCCESS(f"Sent {len(sent)} report(s).")
                if sent
                else "No reports due."
            )
