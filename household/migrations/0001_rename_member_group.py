"""Rename the member group from `finance` to `household` (ADR 0008).

Membership of this group is what the access gate checks, so the rename has
to carry every existing member across — a new empty group would lock both
people out on deploy. Renaming the row in place keeps its members and any
permissions attached to it; passwords and TOTP devices are untouched.

If a `household` group somehow already exists, the members of `finance` are
merged into it rather than failing the deploy.
"""

from django.db import migrations

OLD = "finance"
NEW = "household"


def _move(apps, source, target):
    Group = apps.get_model("auth", "Group")

    old = Group.objects.filter(name=source).first()
    if old is None:
        return

    existing = Group.objects.filter(name=target).first()
    if existing is None:
        old.name = target
        old.save(update_fields=["name"])
        return

    existing.user_set.add(*old.user_set.all())
    existing.permissions.add(*old.permissions.all())
    old.delete()


def forwards(apps, schema_editor):
    _move(apps, OLD, NEW)


def backwards(apps, schema_editor):
    _move(apps, NEW, OLD)


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
