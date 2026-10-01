"""Give the household's members the `household` group (ADR 0008).

Membership of this group is what the access gate checks, so every member of
the old `finance` group is added to it — a new empty group would lock both
people out on deploy. Passwords and TOTP devices are untouched.

**Copied, not renamed.** The `finance` group is left in place, members and
all. A code rollback restores code but not data, and the pre-household code
checks for `finance`: had this renamed the group, rolling back would have
locked both people out of their own finances. The old group is unused by
current code and harmless; a later migration can remove it once rollback to
the pre-household code is no longer a possibility. (The file keeps its
original name because later migrations depend on it.)

If a `household` group already exists, the members are added to it rather
than failing the deploy — check before deploying that nobody unexpected is in
it (household/docs/runbook.md).
"""

from django.db import migrations

OLD = "finance"
NEW = "household"


def forwards(apps, schema_editor):
    Group = apps.get_model("auth", "Group")

    old = Group.objects.filter(name=OLD).first()
    if old is None:
        return

    new, _ = Group.objects.get_or_create(name=NEW)
    new.user_set.add(*old.user_set.all())
    new.permissions.add(*old.permissions.all())


def backwards(apps, schema_editor):
    """Undo the copy, making sure everyone in `household` is in `finance`
    first — so a member added after the deploy isn't stranded by a rollback."""
    Group = apps.get_model("auth", "Group")

    new = Group.objects.filter(name=NEW).first()
    if new is None:
        return

    old, _ = Group.objects.get_or_create(name=OLD)
    old.user_set.add(*new.user_set.all())
    old.permissions.add(*new.permissions.all())
    new.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
