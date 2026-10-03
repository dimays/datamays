from django.db import models

# The same shape as finance's money columns (ADR 0002): Decimal, never float.
# Restated rather than imported — finance's models are off limits here (ADR
# 0009) — and kept identical so an amount can move between the two without
# rounding.
MONEY_MAX_DIGITS = 14
MONEY_DECIMAL_PLACES = 2


def money_field(**kwargs):
    kwargs.setdefault("max_digits", MONEY_MAX_DIGITS)
    kwargs.setdefault("decimal_places", MONEY_DECIMAL_PLACES)
    return models.DecimalField(**kwargs)


class TimestampedModel(models.Model):
    """The household's copy of finance's base — finance's own is off limits
    here (ADR 0009), and two fields are not worth a shared module."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
