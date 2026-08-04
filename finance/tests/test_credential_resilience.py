"""Settings must survive a credential that cannot be decrypted.

A rotated or lost FIELD_ENCRYPTION_KEYS is exactly when someone needs the
settings page — to see which connection is broken and re-authorize it. If
merely listing connections decrypted every secret, that page would 500 and
leave no way back in.
"""

from cryptography.fernet import Fernet
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from finance import crypto
from finance.crypto import DecryptionFailed
from finance.models import AccountConnection

from .factories import make_institution
from .test_access import make_user

OTHER_KEY = Fernet.generate_key().decode()


class CredentialResilienceTests(TestCase):
    def setUp(self):
        call_command("seed_finance_categories", verbosity=0)

        self.user = make_user("david", with_device=True)
        self.institution = make_institution()
        self.connection = AccountConnection.objects.create(
            institution=self.institution,
            label="Byline",
            access_secret="https://user:secret@bridge.simplefin.org/simplefin",
        )

        self.client.force_login(self.user)
        session = self.client.session
        session["otp_device_id"] = TOTPDevice.objects.get(user=self.user).persistent_id
        session.save()

    def test_presence_is_recorded_without_needing_the_key(self):
        self.connection.refresh_from_db()

        self.assertTrue(self.connection.credential_stored)
        self.assertTrue(self.connection.is_syncable)

    def test_erasing_the_secret_clears_the_flag(self):
        self.connection.access_secret = ""
        self.connection.save(update_fields=["access_secret", "updated_at"])

        self.connection.refresh_from_db()
        self.assertFalse(self.connection.credential_stored)
        self.assertFalse(self.connection.is_syncable)

    def test_a_status_only_save_leaves_the_flag_alone(self):
        self.connection.mark_failed("timeout")

        self.connection.refresh_from_db()
        self.assertTrue(self.connection.credential_stored)

    def test_settings_still_loads_when_the_key_no_longer_matches(self):
        crypto._CIPHER_CACHE.clear()

        with override_settings(FIELD_ENCRYPTION_KEYS=[OTHER_KEY]):
            response = self.client.get(reverse("finance:settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Byline")

    def test_connection_detail_still_loads_when_the_key_no_longer_matches(self):
        crypto._CIPHER_CACHE.clear()

        with override_settings(FIELD_ENCRYPTION_KEYS=[OTHER_KEY]):
            response = self.client.get(
                reverse("finance:connection_detail", args=[self.connection.pk])
            )

        self.assertEqual(response.status_code, 200)

    def test_actually_reading_the_secret_still_fails_loudly(self):
        # Degrading gracefully must not mean silently returning nothing.
        crypto._CIPHER_CACHE.clear()

        with override_settings(FIELD_ENCRYPTION_KEYS=[OTHER_KEY]):
            with self.assertRaises(DecryptionFailed):
                AccountConnection.objects.get(pk=self.connection.pk).access_secret

        crypto._CIPHER_CACHE.clear()
