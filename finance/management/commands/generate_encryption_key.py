from cryptography.fernet import Fernet
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Generate a Fernet key suitable for FIELD_ENCRYPTION_KEYS."

    def handle(self, *args, **options):
        # Guidance goes to stderr so the key itself can be piped cleanly.
        self.stderr.write(
            "Add this to FIELD_ENCRYPTION_KEYS (comma-separated; the first key "
            "encrypts, all keys decrypt). Set it locally in .env and in "
            "production with `heroku config:set`. Losing it means re-authorizing "
            "every connection.\n"
        )
        self.stdout.write(Fernet.generate_key().decode())
