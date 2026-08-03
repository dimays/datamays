from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from finance.access import FINANCE_GROUP


class Command(BaseCommand):
    help = (
        "Create (or promote) a user and add them to the finance group. "
        "Membership of that group is what grants access to /finance."
    )

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--email", default="")
        parser.add_argument("--first-name", default="", dest="first_name")

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        username = options["username"]

        group, created_group = Group.objects.get_or_create(name=FINANCE_GROUP)
        if created_group:
            self.stdout.write(f"Created the '{FINANCE_GROUP}' group.")

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": options["email"],
                "first_name": options["first_name"],
            },
        )

        if created:
            # No password is set here, so the account cannot be logged into
            # until one is chosen interactively below.
            password = self._prompt_for_password(username)
            user.set_password(password)
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Created user '{username}'."))
        else:
            self.stdout.write(f"User '{username}' already exists; adding to group.")

        user.groups.add(group)

        self.stdout.write(
            self.style.SUCCESS(
                f"'{username}' can now reach /finance. They will be prompted to "
                "enrol an authenticator app on first sign-in."
            )
        )

    def _prompt_for_password(self, username):
        from getpass import getpass

        for _ in range(3):
            password = getpass(f"Password for {username}: ")
            confirmation = getpass("Confirm: ")

            if password != confirmation:
                self.stderr.write("Passwords did not match.")
                continue

            if len(password) < 12:
                self.stderr.write(
                    "Use at least 12 characters — this guards real account data."
                )
                continue

            return password

        raise CommandError("Could not set a password.")
