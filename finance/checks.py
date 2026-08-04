from django.conf import settings
from django.core.checks import Warning, register


@register()
def encryption_key_configured(app_configs, **kwargs):
    """Warn when FIELD_ENCRYPTION_KEYS is absent.

    Deliberately a warning rather than an error: an unset key only breaks the
    parts of the app that store provider secrets, and escalating it would take
    the whole public site down on deploy. The runtime raises loudly on first
    use instead (see finance.crypto.get_cipher).
    """
    if getattr(settings, "FIELD_ENCRYPTION_KEYS", None):
        return []

    return [
        Warning(
            "FIELD_ENCRYPTION_KEYS is not configured.",
            hint=(
                "Finance provider credentials cannot be stored or read until "
                "this is set. Generate a key with "
                "`python manage.py generate_encryption_key`, then set it as an "
                "environment variable locally and as a Heroku config var in "
                "production."
            ),
            id="finance.W001",
        )
    ]
