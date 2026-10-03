from django.core.management.base import BaseCommand

from household.services.digest import send_due_digests


class Command(BaseCommand):
    help = "Send each morning digest that is due (once per household morning, from 7am)."

    def handle(self, *args, **options):
        sent = send_due_digests()
        if options["verbosity"]:
            self.stdout.write(self.style.SUCCESS(f"Sent {sent} digest{'s' if sent != 1 else ''}."))
