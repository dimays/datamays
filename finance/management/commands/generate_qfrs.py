"""Generate Quarterly Finance Reports.

Run once, by hand, after historical data is loaded — not from the scheduler.
A QFR is meant to reflect complete data for its quarter, and the only person
who knows "backfill is done enough" is the person who just finished doing it.
"""

from django.core.management.base import BaseCommand, CommandError

from finance.dates import household_today
from finance.models import QuarterlyReport
from finance.periods import quarter_containing, quarters_between
from finance.services.qfr import generate_qfr, quarter_is_complete


def parse_quarter_arg(value):
    """'2025-Q1' -> (2025, 1)."""
    try:
        year_part, quarter_part = value.upper().split("-Q")
        year, quarter = int(year_part), int(quarter_part)
    except (ValueError, AttributeError):
        raise CommandError(f"Could not parse {value!r} as YYYY-Qn, e.g. 2025-Q1.")

    if quarter not in (1, 2, 3, 4):
        raise CommandError(f"Quarter must be 1-4 in {value!r}.")

    return year, quarter


class Command(BaseCommand):
    help = (
        "Generate Quarterly Finance Reports. Use --since to backfill every "
        "completed quarter from a starting point through the most recent "
        "one; use --quarter for a single one."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--since",
            metavar="YYYY-Qn",
            help="Backfill every completed quarter from this one through the most recent.",
        )
        parser.add_argument(
            "--quarter",
            metavar="YYYY-Qn",
            help="Generate a single quarter.",
        )
        parser.add_argument(
            "--regenerate",
            action="store_true",
            help="Recompute and overwrite quarters that already have a report.",
        )

    def handle(self, *args, **options):
        if not options["since"] and not options["quarter"]:
            raise CommandError("Pass --since or --quarter.")

        if options["quarter"]:
            targets = [parse_quarter_arg(options["quarter"])]
        else:
            start_year, start_quarter = parse_quarter_arg(options["since"])
            current_year, current_quarter = quarter_containing(household_today())
            end_year, end_quarter = (
                (current_year, current_quarter - 1)
                if current_quarter > 1
                else (current_year - 1, 4)
            )

            if (start_year, start_quarter) > (end_year, end_quarter):
                self.stdout.write("No completed quarters in that range yet.")
                return

            targets = list(
                quarters_between(start_year, start_quarter, end_year, end_quarter)
            )

        generated, reused, skipped, failed = 0, 0, 0, 0

        for year, quarter in targets:
            if not quarter_is_complete(year, quarter):
                skipped += 1
                if options["verbosity"]:
                    self.stdout.write(f"Q{quarter} {year}: not finished yet, skipped.")
                continue

            already_existed = QuarterlyReport.objects.filter(
                year=year, quarter=quarter
            ).exists()

            try:
                report = generate_qfr(year, quarter, force=options["regenerate"])
            except Exception as exc:  # noqa: BLE001
                # One bad quarter — a transient API error, an unexpected data
                # shape — should not stop the rest of a multi-year backfill.
                failed += 1
                self.stderr.write(self.style.ERROR(f"Q{quarter} {year} failed: {exc}"))
                continue

            if already_existed and not options["regenerate"]:
                reused += 1
                if options["verbosity"]:
                    self.stdout.write(f"{report.label}: already existed, left as-is.")
                continue

            generated += 1

            if options["verbosity"]:
                narrated = "with narrative" if report.has_narrative else "metrics only"
                self.stdout.write(self.style.SUCCESS(f"{report.label}: {narrated}"))

        if options["verbosity"]:
            self.stdout.write(
                f"Done: {generated} generated, {reused} already existed, "
                f"{skipped} not yet complete, {failed} failed."
            )

        if failed:
            raise SystemExit(1)
