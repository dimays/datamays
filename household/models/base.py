from django.db import models


class TimestampedModel(models.Model):
    """The household's copy of finance's base — finance's own is off limits
    here (ADR 0009), and two fields are not worth a shared module."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
