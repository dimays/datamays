from django.core.management.base import BaseCommand

from ._chain import run_chain


class Command(BaseCommand):
    help = (
        "The hourly scheduler entry point: finance's hourly chain, then roll "
        "missed chores forward, then send any morning digests now due."
    )

    STEPS = [
        ("finance_hourly", {}),
        ("sweep_chores", {}),
        ("send_digests", {}),
    ]

    def handle(self, *args, **options):
        run_chain(self, self.STEPS, options["verbosity"])
