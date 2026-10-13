from django.core.management.base import BaseCommand, CommandError

from household.services import demo


class Command(BaseCommand):
    help = "Print the current second-factor code for a demo member (local SQLite only)."

    def add_arguments(self, parser):
        parser.add_argument("username")

    def handle(self, *args, **options):
        try:
            demo.ensure_local_database()
            self.stdout.write(demo.current_totp_code(options["username"]))
        except demo.NotALocalDatabase as exc:
            raise CommandError(str(exc))
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"No demo authenticator for {options['username']}: {exc}")
