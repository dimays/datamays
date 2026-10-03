"""Settings for clicking around the site locally, against a throwaway database.

The repository's .env points DATABASE_URL at the deployed Postgres, so
`runserver` under the default settings reads and writes production data.
`settings_test` avoids that for the test suite, but its in-memory database
vanishes with the process — useless for a server you want to sign in to.

This module pins to a file-based SQLite database next to manage.py
(`db.local.sqlite3`, gitignored), silences Sentry, prints email to the
console instead of sending it, and keeps the LLM steps offline. Fill it with
fictional data using `seed_household_demo`.

Usage:
    uv run python manage.py migrate --settings=datamays.settings_local
    uv run python manage.py seed_household_demo --settings=datamays.settings_local
    uv run python manage.py runserver --settings=datamays.settings_local
"""

import os

# Both set before the star-import. Sentry initializes at import time and must
# never report local tinkering as a production error; WORKING_ENV has to be
# "dev" for localhost to be an allowed host and for the placeholder
# SECRET_KEY to be accepted. setdefault, and .env loading never overrides an
# existing variable, so an explicit shell value still wins.
os.environ["SENTRY_DSN"] = ""
os.environ.setdefault("WORKING_ENV", "dev")

import sentry_sdk  # noqa: E402
from cryptography.fernet import Fernet  # noqa: E402

from .settings import *  # noqa: E402,F401,F403
from .settings import BASE_DIR, STORAGES  # noqa: E402

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.local.sqlite3",
    }
}

sentry_sdk.init(dsn=None)

DEBUG = True
SECURE_SSL_REDIRECT = False

# Digest and report emails land in the runserver output, where they can be
# read, rather than in a real inbox.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# The categorizer and QFR narrator both fall back to their offline paths
# without a key, so local data never leaves the machine.
OPENAI_API_KEY = ""

# Generated per process, like settings_test: no usable key is ever committed
# to this public repo. Only provider connections are encrypted, and the demo
# data has none.
FIELD_ENCRYPTION_KEYS = [Fernet.generate_key().decode()]

# The manifest storage needs collectstatic to have run first; runserver serves
# straight from static/ instead.
STORAGES = {
    **STORAGES,
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
