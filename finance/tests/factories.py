"""Small builders so tests read as intent rather than setup."""

from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User

from finance.models import (
    Account,
    AccountType,
    Category,
    CategoryKind,
    Institution,
    Transaction,
)


def make_institution(name="Byline Bank", **kwargs):
    # get_or_create so tests that build several accounts without naming an
    # institution share one rather than colliding on the unique slug.
    institution, _ = Institution.objects.get_or_create(
        name=name,
        defaults={"slug": kwargs.pop("slug", name.lower().replace(" ", "-")), **kwargs},
    )
    return institution


def make_account(institution=None, **kwargs):
    kwargs.setdefault("name", "Joint Checking")
    kwargs.setdefault("account_type", AccountType.CHECKING)

    return Account.objects.create(
        institution=institution or make_institution(), **kwargs
    )


def make_category(name="Groceries", slug="food-groceries", **kwargs):
    kwargs.setdefault("kind", CategoryKind.EXPENSE)
    return Category.objects.create(name=name, slug=slug, **kwargs)


def make_transaction(account=None, **kwargs):
    kwargs.setdefault("posted_on", date(2026, 4, 15))
    kwargs.setdefault("amount", Decimal("-42.50"))
    kwargs.setdefault("description_raw", "MARIANOS #1234 CHICAGO IL")

    return Transaction.objects.create(account=account or make_account(), **kwargs)


def make_user(username="david", **kwargs):
    return User.objects.create_user(username=username, password="test-password-1234", **kwargs)
