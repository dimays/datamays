"""Symmetric field encryption for finance secrets.

Provider access URLs embed HTTP Basic credentials, so they must never sit in
the database as plaintext. Values are encrypted with Fernet (AES-128-CBC plus
an HMAC-SHA256 authentication tag) using keys supplied through the
``FIELD_ENCRYPTION_KEYS`` setting.

The first key encrypts; every key can decrypt. That is what makes rotation
possible: prepend a new key, re-save the affected rows, then drop the old key.
"""

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.conf import settings

# Ciphers are cached per key tuple rather than globally so that tests using
# override_settings get a cipher matching the keys actually in force.
_CIPHER_CACHE: dict[tuple[str, ...], MultiFernet] = {}


class EncryptionKeyMissing(ImproperlyConfigured):
    """Raised when encrypted data is touched without a configured key."""


class DecryptionFailed(Exception):
    """Raised when stored ciphertext cannot be decrypted by any known key."""


def get_cipher() -> MultiFernet:
    keys = tuple(getattr(settings, "FIELD_ENCRYPTION_KEYS", ()) or ())

    if not keys:
        raise EncryptionKeyMissing(
            "FIELD_ENCRYPTION_KEYS is not set, so finance secrets cannot be "
            "read or written. Generate a key with "
            "`python manage.py generate_encryption_key` and set it as an "
            "environment variable (a Heroku config var in production)."
        )

    if keys not in _CIPHER_CACHE:
        try:
            _CIPHER_CACHE[keys] = MultiFernet([Fernet(key) for key in keys])
        except (ValueError, TypeError) as exc:
            raise ImproperlyConfigured(
                f"FIELD_ENCRYPTION_KEYS contains an invalid Fernet key: {exc}"
            ) from exc

    return _CIPHER_CACHE[keys]


def encrypt(value: str) -> str:
    return get_cipher().encrypt(str(value).encode()).decode()


def decrypt(token: str) -> str:
    try:
        return get_cipher().decrypt(str(token).encode()).decode()
    except InvalidToken as exc:
        raise DecryptionFailed(
            "Stored value could not be decrypted with any key in "
            "FIELD_ENCRYPTION_KEYS. The key was most likely rotated or lost; "
            "re-authorize the affected connection to store a fresh secret."
        ) from exc


class EncryptedTextField(models.TextField):
    """A TextField whose value is encrypted at rest.

    Stored values are opaque ciphertext, so this field cannot be filtered,
    ordered, or indexed on. Keep a separate plaintext discriminator (a label,
    an account mask) on the model when rows need to be looked up.
    """

    def get_prep_value(self, value):
        if value is None or value == "":
            return value
        return encrypt(value)

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        return decrypt(value)
