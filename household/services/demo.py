"""A fictional household to click around in locally.

Browser QA needs a signed-in session over realistic-looking data, and the only
real data lives in production. This builds a stand-in: two members, a demo
bank, four months of ordinary spending, and budgets rolled up over it. Each
build phase extends it with its own section's data.

**Everything here is invented.** The repository is public, so no name,
merchant, or amount in this file may come from the real household's records.

It refuses to run anywhere but SQLite. The local `.env` points at production
Postgres, and a seed that flushes the database is the last command that should
ever be able to reach it.
"""

import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import connection, transaction
from django.utils import timezone
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice

from finance.models import (
    Account,
    AccountBalanceSnapshot,
    AccountType,
    BalanceSource,
    Budget,
    Category,
    CategorySource,
    Institution,
    Transaction,
)
from finance.services.rollups import backfill_budget
from household.access import HOUSEHOLD_GROUP
from household.dates import household_today

# Local-only sign-in for the demo members. Deliberately written down: the
# seed refuses to run against anything but a local SQLite file, so these can
# never become credentials for real data.
DEMO_PASSWORD = "household-demo-2026"

# The RFC 6238 reference secret ("12345678901234567890" in hex) — a published
# test vector, not a secret. `demo_totp_code` turns it into a current code.
DEMO_TOTP_KEY = "3132333435363738393031323334353637383930"

DEMO_MEMBERS = [
    {"username": "david", "first_name": "David", "email": "david@example.com"},
    {"username": "maddie", "first_name": "Maddie", "email": "maddie@example.com"},
]

DEMO_INSTITUTION = "Demo Credit Union"

HISTORY_DAYS = 120

# Merchant, category slug, typical amount, and roughly how many days apart.
# Amounts jitter by up to 25% so the charts have some texture.
RECURRING_SPEND = [
    ("FRESH MARKET #22", "food-groceries", "96.00", 6),
    ("CORNER BISTRO", "food-restaurants", "54.00", 9),
    ("DAILY GRIND COFFEE", "food-coffee", "6.25", 3),
    ("QUICKFUEL 118", "transport-fuel", "44.00", 11),
    ("HOME CENTER #481", "housing-maintenance", "38.00", 24),
    ("STREAMFLIX", "entertainment-streaming", "15.49", 30),
]

MONTHLY_BILLS = [
    # Day of month, merchant, category slug, amount.
    (1, "HOMETOWN MORTGAGE CO", "housing-mortgage", "1840.00"),
    (12, "CITY UTILITIES", "housing-utilities", "142.00"),
    (18, "FIBERNET", "housing-internet-phone", "70.00"),
]

DEMO_BUDGETS = [
    # Name, monthly target, category slugs.
    ("Groceries", "800.00", ["food-groceries"]),
    ("Eating out", "300.00", ["food-restaurants", "food-coffee"]),
    ("Home upkeep", "200.00", ["housing-maintenance", "housing-improvement"]),
]


class NotALocalDatabase(Exception):
    pass


def ensure_local_database():
    """Stop unless the default connection is SQLite.

    Checked against the live connection, not the settings module's name, so a
    DATABASE_URL leaking in by some other route is still caught.
    """
    if connection.vendor != "sqlite":
        raise NotALocalDatabase(
            f"Refusing to run against a {connection.vendor} database. "
            "Use --settings=datamays.settings_local."
        )


def is_seeded():
    return Institution.objects.filter(name=DEMO_INSTITUTION).exists()


def current_totp_code(username):
    device = TOTPDevice.objects.get(user__username=username, confirmed=True)
    token = TOTP(
        device.bin_key, device.step, device.t0, device.digits, device.drift
    ).token()

    # token() is an int, so a code with a leading zero would lose a digit.
    return f"{token:0{device.digits}d}"


@transaction.atomic
def seed(*, rng=None):
    """Build the demo household. Returns a short summary for the command."""
    ensure_local_database()
    rng = rng or random.Random(2026)

    call_command("seed_finance_categories", verbosity=0)

    members = _members()
    accounts = _accounts()
    transactions = _transactions(accounts, rng)
    _balance_history(accounts)
    budgets = _budgets()
    chores = _chores(members)

    return {
        "members": [member.username for member in members],
        "accounts": len(accounts),
        "transactions": transactions,
        "budgets": len(budgets),
        "chores": chores,
    }


def _members():
    User = get_user_model()
    group, _ = Group.objects.get_or_create(name=HOUSEHOLD_GROUP)
    members = []

    for spec in DEMO_MEMBERS:
        user, created = User.objects.get_or_create(
            username=spec["username"],
            defaults={"first_name": spec["first_name"], "email": spec["email"]},
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()

        user.groups.add(group)
        TOTPDevice.objects.get_or_create(
            user=user,
            name="Demo authenticator",
            defaults={"key": DEMO_TOTP_KEY, "confirmed": True},
        )
        members.append(user)

    return members


def _accounts():
    institution = Institution.objects.create(name=DEMO_INSTITUTION, slug="demo-credit-union")

    specs = [
        ("Joint Checking", AccountType.CHECKING, "4250.00", "1001"),
        ("High-Yield Savings", AccountType.SAVINGS, "18400.00", "1002"),
        ("Rewards Card", AccountType.CREDIT_CARD, "-1120.00", "4242"),
    ]

    return {
        account_type: Account.objects.create(
            institution=institution,
            name=name,
            account_type=account_type,
            mask=mask,
            current_balance=Decimal(balance),
            balance_as_of=timezone.now(),
        )
        for name, account_type, balance, mask in specs
    }


def _transactions(accounts, rng):
    today = household_today()
    start = today - timedelta(days=HISTORY_DAYS)
    categories = {category.slug: category for category in Category.objects.all()}
    checking = accounts[AccountType.CHECKING]
    card = accounts[AccountType.CREDIT_CARD]
    rows = []

    def add(account, posted_on, merchant, slug, amount):
        rows.append(
            Transaction(
                account=account,
                posted_on=posted_on,
                amount=amount,
                description_raw=merchant,
                merchant=merchant.title(),
                category=categories[slug],
                category_source=CategorySource.MANUAL,
            )
        )

    for merchant, slug, typical, every in RECURRING_SPEND:
        day = start + timedelta(days=rng.randrange(every))
        while day <= today:
            jitter = Decimal(str(round(rng.uniform(0.75, 1.25), 2)))
            add(card, day, merchant, slug, -(Decimal(typical) * jitter).quantize(Decimal("0.01")))
            day += timedelta(days=max(1, every + rng.randint(-1, 2)))

    day = start
    while day <= today:
        for bill_day, merchant, slug, amount in MONTHLY_BILLS:
            if day.day == bill_day:
                add(checking, day, merchant, slug, -Decimal(amount))

        # Paid every other Friday.
        if day.weekday() == 4 and (day - start).days // 7 % 2 == 0:
            add(checking, day, "ACME PAYROLL DIRECT DEP", "income-salary", Decimal("3150.00"))

        day += timedelta(days=1)

    # One lumpy home-improvement purchase, the kind a project will later claim.
    add(card, today - timedelta(days=21), "HOME CENTER #481", "housing-improvement", Decimal("-412.87"))

    # bulk_create skips save(), which is where a fingerprint is normally
    # derived — without one every row collides on the uniqueness constraint.
    for row in rows:
        row.ensure_fingerprint()

    Transaction.objects.bulk_create(rows)
    return len(rows)


def _balance_history(accounts):
    """A daily balance per account, walked backwards from today's.

    Charts read balance history from snapshots, not from summed transactions,
    so the demo needs the snapshots written out explicitly.
    """
    today = household_today()
    snapshots = []

    for account in accounts.values():
        by_day = {}
        for posted_on, amount in account.transactions.values_list("posted_on", "amount"):
            by_day[posted_on] = by_day.get(posted_on, Decimal("0")) + amount

        balance = account.current_balance
        for offset in range(HISTORY_DAYS + 1):
            day = today - timedelta(days=offset)
            snapshots.append(
                AccountBalanceSnapshot(
                    account=account, as_of=day, current=balance, source=BalanceSource.CSV
                )
            )
            balance -= by_day.get(day, Decimal("0"))

    AccountBalanceSnapshot.objects.bulk_create(snapshots)


def _budgets():
    budgets = []

    for name, amount, slugs in DEMO_BUDGETS:
        budget = Budget.objects.create(name=name, amount=Decimal(amount))
        budget.categories.set(Category.objects.filter(slug__in=slugs))
        backfill_budget(budget, periods_back=3)
        budgets.append(budget)

    return budgets


def _chores(members):
    """A spread of chores that exercises every state a screen can show:
    overdue, due today, coming up this week, later, whenever, shared, one
    person's, the other's, paused, and some done history."""
    from datetime import datetime, time

    from household.dates import household_timezone
    from household.models import Chore
    from household.scheduling import Anchor, Frequency, MonthlyMode
    from household.services import occurrences

    david, maddie = members
    today = household_today()
    days = lambda n: today + timedelta(days=n)  # noqa: E731

    def chore(owner, title, *, assignee="owner", start_today=None, **fields):
        assignee = owner if assignee == "owner" else assignee
        made = Chore.objects.create(owner=owner, assignee=assignee, title=title, **fields)
        occurrences.reschedule(made, today=start_today or today)
        return made

    # David's
    chore(david, "Take out trash and recycling", frequency=Frequency.WEEKLY, starts_on=days(-2 - today.weekday() % 7 + 7))
    chore(david, "Unload the dishwasher", frequency=Frequency.DAILY, starts_on=today)
    chore(david, "Call the plumber about the slow drain", starts_on=days(-3))
    chore(david, "Water the plants", frequency=Frequency.WEEKLY, weekdays=[0, 3], starts_on=days(-14), others_can_manage=True)
    chore(david, "Organize the garage", starts_on=None)

    # Maddie's
    chore(maddie, "Walk the dog", frequency=Frequency.DAILY, starts_on=today)
    chore(maddie, "Renew car registration", starts_on=days(4), deadline=days(20))
    chore(maddie, "Book dentist appointments", starts_on=days(6))
    chore(maddie, "Plan the holiday card list", starts_on=days(25))

    # Shared household chores
    chore(None, "Replace the furnace filter", frequency=Frequency.DAILY, interval=90,
          anchor=Anchor.AFTER_COMPLETION, starts_on=days(-12))
    chore(None, "Clean the gutters", frequency=Frequency.YEARLY, starts_on=days(5), deadline_offset_days=14)
    chore(None, "Mow the lawn", assignee=david, frequency=Frequency.WEEKLY,
          anchor=Anchor.AFTER_COMPLETION, starts_on=days(2), season_start_month=4, season_end_month=10)
    paused = chore(None, "Wash the windows", frequency=Frequency.MONTHLY, starts_on=days(10))
    paused.is_active = False
    paused.save()
    occurrences.reschedule(paused, today=today)

    # Some history: a monthly fridge clean done for the last three months,
    # by alternating people, before the current one.
    fridge = chore(
        None, "Deep clean the fridge", frequency=Frequency.MONTHLY,
        monthly_mode=MonthlyMode.DAY, starts_on=days(-90), start_today=days(-90),
    )
    for index in range(3):
        current = fridge.occurrences.get(status="open")
        done_on = current.due_on + timedelta(days=1)
        when = datetime.combine(done_on, time(19), tzinfo=household_timezone())
        occurrences.complete(current, by=(david, maddie)[index % 2], now=when, today=done_on)

    return Chore.objects.count()
