"""Settings for running the test suite.

The repository's .env points DATABASE_URL at the deployed Postgres, so running
`manage.py test` against the default settings asks that server to create a test
database. This module pins tests to a throwaway in-memory SQLite database and
silences Sentry, so a test run can never touch production.

Usage:
    uv run python manage.py test --settings=datamays.settings_test
"""

import os

# Cleared before the star-import so settings.py never initialises a real
# Sentry client — a test run must not report into production error tracking.
os.environ["SENTRY_DSN"] = ""

import sentry_sdk  # noqa: E402
from cryptography.fernet import Fernet  # noqa: E402

from .settings import *  # noqa: E402,F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# settings.py initialises Sentry at import time; re-initialising with no DSN
# stops test failures from being reported as production errors.
sentry_sdk.init(dsn=None)

# Fast, deterministic hashing — these tests never exercise password strength.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Generated per run so no usable key is ever committed to this public repo.
FIELD_ENCRYPTION_KEYS = [Fernet.generate_key().decode()]

SECURE_SSL_REDIRECT = False

# The manifest-hashed static storage needs collectstatic to have already run
# to resolve {% static %} lookups — never true for a test run, so tests use
# plain unhashed storage instead.
STORAGES = {
    **STORAGES,
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
