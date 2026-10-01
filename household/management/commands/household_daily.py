from django.core.management.base import BaseCommand

from ._chain import run_chain


class Command(BaseCommand):
    help = "The daily scheduler entry point: finance's daily chain, then roll missed chores forward."

    STEPS = [
        ("finance_daily", {}),
        ("sweep_chores", {}),
    ]

    def handle(self, *args, **options):
        run_chain(self, self.STEPS, options["verbosity"])
