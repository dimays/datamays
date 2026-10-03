"""A short starter list of common home maintenance, to adopt or ignore.

Deliberately generic — the repository is public, and a list of *this*
house's systems belongs in the database, not here. Deliberately short: the
decision was to start simple, and anything missing is one form away.

Each entry becomes a household-owned chore plus a maintenance item when
adopted (`services/maintenance.py::adopt`). Dates are month/day pairs and
resolve to the next such date from the day it is adopted.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from .models import MaintenanceArea
from .scheduling import Anchor, Frequency


@dataclass(frozen=True)
class LibraryEntry:
    key: str
    title: str
    area: str
    frequency: str
    interval: int = 1
    anchor: str = Anchor.FIXED
    month_day: tuple | None = None  # for fixed yearly entries: (month, day)
    deadline_offset_days: int | None = None
    instructions: str = ""
    supplies: str = ""
    estimated_cost: Decimal | None = None
    extras: dict = field(default_factory=dict)


LIBRARY = [
    LibraryEntry(
        key="furnace-filter",
        title="Replace the furnace filter",
        area=MaintenanceArea.HVAC,
        frequency=Frequency.DAILY,
        interval=90,
        anchor=Anchor.AFTER_COMPLETION,
        instructions="Turn the system off, slide out the old filter, and fit the new one with the airflow arrow pointing toward the furnace.",
        supplies="The filter size is printed on the edge of the old one.",
        estimated_cost=Decimal("25.00"),
    ),
    LibraryEntry(
        key="test-detectors",
        title="Test the smoke and CO detectors",
        area=MaintenanceArea.SAFETY,
        frequency=Frequency.MONTHLY,
        instructions="Hold each test button until it sounds.",
    ),
    LibraryEntry(
        key="detector-batteries",
        title="Replace smoke and CO detector batteries",
        area=MaintenanceArea.SAFETY,
        frequency=Frequency.YEARLY,
        month_day=(11, 1),
        supplies="Check each detector for the battery type.",
        estimated_cost=Decimal("15.00"),
    ),
    LibraryEntry(
        key="outdoor-water-off",
        title="Shut off and drain the outdoor faucets",
        area=MaintenanceArea.PLUMBING,
        frequency=Frequency.YEARLY,
        month_day=(10, 15),
        deadline_offset_days=21,
        instructions="Close the indoor shut-off valve for each outdoor faucet, then open the outdoor tap to drain the line. Do it before the first hard freeze.",
    ),
    LibraryEntry(
        key="outdoor-water-on",
        title="Turn the outdoor faucets back on",
        area=MaintenanceArea.PLUMBING,
        frequency=Frequency.YEARLY,
        month_day=(4, 15),
        deadline_offset_days=21,
        instructions="Close the outdoor tap, then open the indoor shut-off valve. Check for leaks at the first use of the hose.",
    ),
    LibraryEntry(
        key="gutters",
        title="Clean the gutters",
        area=MaintenanceArea.EXTERIOR,
        frequency=Frequency.MONTHLY,
        interval=6,
        month_day=(4, 30),
        estimated_cost=Decimal("0.00"),
    ),
    LibraryEntry(
        key="dryer-vent",
        title="Clean the dryer vent",
        area=MaintenanceArea.APPLIANCES,
        frequency=Frequency.YEARLY,
        month_day=(3, 1),
        instructions="Disconnect the duct behind the dryer and brush it out end to end, including the outside flap.",
    ),
    LibraryEntry(
        key="water-heater",
        title="Flush the water heater",
        area=MaintenanceArea.PLUMBING,
        frequency=Frequency.YEARLY,
        month_day=(9, 1),
        instructions="Turn off the heat source, attach a hose to the drain valve, and drain a few gallons until the water runs clear.",
    ),
    LibraryEntry(
        key="range-hood",
        title="Clean the range hood filter",
        area=MaintenanceArea.APPLIANCES,
        frequency=Frequency.MONTHLY,
        interval=3,
        anchor=Anchor.AFTER_COMPLETION,
        instructions="Soak in hot water with dish soap and baking soda, then rinse.",
    ),
    LibraryEntry(
        key="fridge-coils",
        title="Vacuum the refrigerator coils",
        area=MaintenanceArea.APPLIANCES,
        frequency=Frequency.YEARLY,
        month_day=(6, 1),
    ),
    LibraryEntry(
        key="ac-service",
        title="Service the air conditioner",
        area=MaintenanceArea.HVAC,
        frequency=Frequency.YEARLY,
        month_day=(5, 1),
        deadline_offset_days=30,
        instructions="Clear debris around the outdoor unit and book a tune-up before the first hot week.",
        estimated_cost=Decimal("150.00"),
    ),
]

BY_KEY = {entry.key: entry for entry in LIBRARY}
