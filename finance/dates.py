"""What "today" means for this household.

The project runs on `TIME_ZONE = 'UTC'`, which is right for storage and right
for the public site. It is wrong for a budget. Between roughly 7pm and midnight
Chicago time, UTC has already rolled over, so `timezone.localdate()` returns
tomorrow — and an evening grocery run on 31 August would count against
September's budget, on the wrong side of a period boundary the app treats as
authoritative.

Every date decision in the finance app goes through here instead: budget
periods, alert period gates, dashboard ranges, "recent" filters. Storage is
untouched — datetimes remain UTC-aware, as Django intends.

Deliberately scoped to this app rather than flipping the project's TIME_ZONE,
which would also change how the public site renders every timestamp.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

DEFAULT_TIME_ZONE = "America/Chicago"


def household_timezone() -> ZoneInfo:
    return ZoneInfo(getattr(settings, "FINANCE_TIME_ZONE", DEFAULT_TIME_ZONE))


def household_today() -> date:
    """The current date where the household actually lives."""
    return timezone.now().astimezone(household_timezone()).date()


def to_household_date(value) -> date:
    """The household-local date of an aware datetime."""
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.astimezone(household_timezone()).date()

    return value
