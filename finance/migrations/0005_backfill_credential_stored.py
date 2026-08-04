from django.db import migrations


def backfill(apps, schema_editor):
    """Set the flag for connections that already hold a credential.

    Uses a SQL-level update against the ciphertext column, so no decryption
    happens and the migration cannot fail on a rotated or missing key.
    """
    AccountConnection = apps.get_model("finance", "AccountConnection")

    AccountConnection.objects.exclude(access_secret="").update(credential_stored=True)


def unset(apps, schema_editor):
    AccountConnection = apps.get_model("finance", "AccountConnection")
    AccountConnection.objects.update(credential_stored=False)


class Migration(migrations.Migration):
    dependencies = [("finance", "0004_accountconnection_credential_stored")]

    operations = [migrations.RunPython(backfill, unset)]
