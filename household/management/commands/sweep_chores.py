from django.core.management.base import BaseCommand

from household.services.occurrences import sweep


class Command(BaseCommand):
    help = (
        "Mark fixed-schedule chores missed once their next due date arrives, "
        "and open the new one. Screens apply the same rule on read; this keeps "
        "the history accurate for chores nobody has opened."
    )

    def handle(self, *args, **options):
        changed = sweep()
        if options["verbosity"]:
            self.stdout.write(self.style.SUCCESS(f"Rolled {changed} chores forward."))
