from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from finance.models import AccountConnection, Institution, Provider
from finance.providers.base import ProviderError
from finance.providers.simplefin import claim_access_url


class Command(BaseCommand):
    help = (
        "Exchange a SimpleFIN setup token for an access URL and store it "
        "encrypted. Get a token from https://bridge.simplefin.org/ after "
        "authorizing the institution."
    )

    def add_arguments(self, parser):
        parser.add_argument("institution", help="Institution name, e.g. 'Byline Bank'.")
        parser.add_argument(
            "--label", default="", help="How the connection appears in settings."
        )
        parser.add_argument(
            "--token",
            default="",
            help="The setup token. Omitted, it is read from stdin without echoing.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        token = options["token"] or self._prompt_for_token()

        try:
            access_url = claim_access_url(token)
        except ProviderError as exc:
            raise CommandError(str(exc))

        institution, created = Institution.objects.get_or_create(
            name=options["institution"],
            defaults={
                "slug": slugify(options["institution"]),
                "provider": Provider.SIMPLEFIN,
            },
        )

        if created:
            self.stdout.write(f"Created institution '{institution.name}'.")

        connection = AccountConnection.objects.create(
            institution=institution,
            label=options["label"] or f"{institution.name} (SimpleFIN)",
            provider=Provider.SIMPLEFIN,
            access_secret=access_url,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Stored connection #{connection.pk}. Pull the first 90 days with:\n"
                f"  python manage.py sync_accounts --connection {connection.pk} --manual"
            )
        )

    def _prompt_for_token(self):
        from getpass import getpass

        # getpass keeps the token out of shell history and off the screen; it
        # is a bearer credential until it is claimed.
        token = getpass("SimpleFIN setup token: ").strip()

        if not token:
            raise CommandError("No setup token supplied.")

        return token
