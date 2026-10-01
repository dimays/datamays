"""Every household view, one module per screen area, re-exported here."""

from .auth import HouseholdLoginView, HouseholdLogoutView, OTPSetupView, OTPVerifyView
from .base import HouseholdPageMixin, HouseholdView, PageTitleMixin
from .chores import (
    ChecklistView,
    ChoreCreateView,
    ChoreDeleteView,
    ChoreDetailView,
    ChoreListView,
    ChoreUpdateView,
    OccurrenceActionView,
    PartnerToggleView,
    SchedulePreviewView,
)
from .maintenance import (
    LibraryAdoptView,
    LibraryView,
    UpkeepCreateView,
    UpkeepDeleteView,
    UpkeepDetailView,
    UpkeepListView,
    UpkeepUpdateView,
)
from .prefs import HouseholdPreferencesView
from .today import TodayView

__all__ = [
    "ChecklistView",
    "ChoreCreateView",
    "ChoreDeleteView",
    "ChoreDetailView",
    "ChoreListView",
    "ChoreUpdateView",
    "HouseholdLoginView",
    "HouseholdLogoutView",
    "HouseholdPageMixin",
    "HouseholdPreferencesView",
    "HouseholdView",
    "LibraryAdoptView",
    "LibraryView",
    "OTPSetupView",
    "OTPVerifyView",
    "OccurrenceActionView",
    "PageTitleMixin",
    "PartnerToggleView",
    "SchedulePreviewView",
    "TodayView",
    "UpkeepCreateView",
    "UpkeepDeleteView",
    "UpkeepDetailView",
    "UpkeepListView",
    "UpkeepUpdateView",
]
