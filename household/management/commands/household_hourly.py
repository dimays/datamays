from django.core.management.base import BaseCommand

from ._chain import run_chain


class Command(BaseCommand):
    help = (
        "The hourly scheduler entry point: roll missed chores forward, send any "
        "morning digests now due, then run finance's hourly chain."
    )

    # Household steps first: neither needs the bank sync, and a slow or
    # failing sync shouldn't delay the morning email. Found in review.
    STEPS = [
        ("sweep_chores", {}),
        ("send_digests", {}),
        ("finance_hourly", {}),
    ]

    def handle(self, *args, **options):
        run_chain(self, self.STEPS, options["verbosity"])
