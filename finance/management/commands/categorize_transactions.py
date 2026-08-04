from django.core.management.base import BaseCommand

from finance.models import Transaction
from finance.services.categorize import categorise_transactions


class Command(BaseCommand):
    help = (
        "Categorise transactions that have no category yet. Rules and "
        "remembered merchants run first; only genuinely new merchants reach "
        "the classifier."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--recategorize",
            action="store_true",
            help="Also revisit transactions already categorised by the classifier.",
        )
        parser.add_argument(
            "--no-transfers",
            action="store_true",
            help="Skip transfer pairing.",
        )
        parser.add_argument("--limit", type=int, help="Cap how many are processed.")

    def handle(self, *args, **options):
        queryset = None

        if options["recategorize"]:
            queryset = Transaction.objects.filter(is_transfer=False).exclude(
                category_source="manual"
            )

        if options["limit"]:
            base = queryset if queryset is not None else Transaction.objects.filter(
                category__isnull=True, is_transfer=False
            )
            queryset = base[: options["limit"]]

        summary = categorise_transactions(
            queryset=queryset, detect_transfers=not options["no_transfers"]
        )

        if options["verbosity"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Transfers paired: {summary.transfers} · "
                    f"by rule: {summary.by_rule} · "
                    f"remembered: {summary.by_memo} · "
                    f"classified: {summary.by_classifier} · "
                    f"needs review: {summary.needs_review} · "
                    f"unmatched: {summary.unmatched}"
                )
            )
