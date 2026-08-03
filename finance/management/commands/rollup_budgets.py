from django.core.management.base import BaseCommand

from finance.models import Budget
from finance.services.rollups import backfill_budget, roll_up_all


class Command(BaseCommand):
    help = "Recompute budget actuals for the current period."

    def add_arguments(self, parser):
        parser.add_argument(
            "--backfill",
            type=int,
            metavar="PERIODS",
            help="Also recompute this many past periods, for the history charts.",
        )
        parser.add_argument(
            "--include-inactive",
            action="store_true",
            help="Include paused budgets.",
        )

    def handle(self, *args, **options):
        if options["backfill"]:
            budgets = Budget.objects.all()

            if not options["include_inactive"]:
                budgets = budgets.filter(is_active=True)

            periods = [
                period
                for budget in budgets
                for period in backfill_budget(budget, options["backfill"])
            ]
        else:
            periods = roll_up_all(include_inactive=options["include_inactive"])

        if options["verbosity"]:
            over = sum(1 for period in periods if period.is_over)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Rolled up {len(periods)} budget periods ({over} over target)."
                )
            )
