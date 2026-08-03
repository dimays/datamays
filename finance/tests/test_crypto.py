from cryptography.fernet import Fernet
from django.test import SimpleTestCase, override_settings

from finance import crypto
from finance.crypto import DecryptionFailed, EncryptionKeyMissing, decrypt, encrypt

KEY_A = Fernet.generate_key().decode()
KEY_B = Fernet.generate_key().decode()


@override_settings(FIELD_ENCRYPTION_KEYS=[KEY_A])
class EncryptionTests(SimpleTestCase):
    def test_round_trip(self):
        secret = "https://user:pass@bridge.simplefin.org/simplefin"
        self.assertEqual(decrypt(encrypt(secret)), secret)

    def test_ciphertext_does_not_leak_plaintext(self):
        token = encrypt("https://user:hunter2@bridge.simplefin.org/simplefin")
        self.assertNotIn("hunter2", token)
        self.assertNotIn("simplefin", token)

    def test_encryption_is_non_deterministic(self):
        # Fernet embeds a random IV, so identical inputs must not produce
        # identical ciphertext — otherwise equal secrets would be linkable.
        self.assertNotEqual(encrypt("same"), encrypt("same"))


class KeyHandlingTests(SimpleTestCase):
    def setUp(self):
        # The cipher cache is keyed on the key tuple, so clearing it keeps
        # these cases independent of test ordering.
        crypto._CIPHER_CACHE.clear()

    @override_settings(FIELD_ENCRYPTION_KEYS=[])
    def test_missing_key_raises_actionable_error(self):
        with self.assertRaises(EncryptionKeyMissing):
            encrypt("anything")

    def test_rotation_decrypts_values_written_with_an_older_key(self):
        with override_settings(FIELD_ENCRYPTION_KEYS=[KEY_A]):
            token = encrypt("written-under-key-a")

        # New key first (it now encrypts), old key retained for reads.
        with override_settings(FIELD_ENCRYPTION_KEYS=[KEY_B, KEY_A]):
            self.assertEqual(decrypt(token), "written-under-key-a")

    def test_dropping_a_key_fails_loudly_rather_than_silently(self):
        with override_settings(FIELD_ENCRYPTION_KEYS=[KEY_A]):
            token = encrypt("written-under-key-a")

        with override_settings(FIELD_ENCRYPTION_KEYS=[KEY_B]):
            with self.assertRaises(DecryptionFailed):
                decrypt(token)
