"""What "today" means for this household — now owned by the household shell.

The implementation moved to `household/dates.py` when finance became one
section of Mays Household (ADR 0008). Re-exported here so the many finance
call sites that import from `..dates` are unchanged. The rule is the same:
never `timezone.localdate()` — see ADR 0004.
"""

from household.dates import (  # noqa: F401
    DEFAULT_TIME_ZONE,
    household_start_of_day,
    household_timezone,
    household_today,
    to_household_date,
)
