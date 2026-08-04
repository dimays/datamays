"""Shared conventions for the finance models.

Two rules hold everywhere in this app, and most of the arithmetic elsewhere
assumes them:

**Money is Decimal, never float.** `money_field()` is the only way money enters
a model. Binary floats cannot represent 0.10 exactly, and a budget that drifts
by a cent a month is worse than useless.

**Signs are from the household's point of view.** Money leaving is negative,
money arriving is positive — on every account type, including credit cards.
Balances follow the same rule: assets are positive, liabilities are negative,
so a set of balances sums directly to net worth without special-casing. It is
the provider adapter's job to normalise into this convention at the boundary,
never the reporting code's job to guess.
"""

from django.db import models

MONEY_MAX_DIGITS = 14
MONEY_DECIMAL_PLACES = 2


class Owner(models.TextChoices):
    """Whose an account or institution is, for the household's own bookkeeping.

    Not an access-control concept — both of you can see and edit everything
    regardless of this value. It exists so "whose 401(k) is this" is a fact
    on the record instead of something inferred from the account name.
    """

    DAVID = "david", "David"
    MADDIE = "maddie", "Maddie"
    JOINT = "joint", "Joint"


def money_field(**kwargs):
    kwargs.setdefault("max_digits", MONEY_MAX_DIGITS)
    kwargs.setdefault("decimal_places", MONEY_DECIMAL_PLACES)
    return models.DecimalField(**kwargs)


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
