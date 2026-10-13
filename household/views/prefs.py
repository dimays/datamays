from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import UpdateView

from ..forms.prefs import HouseholdPreferenceForm
from ..models import HouseholdPreference
from .base import HouseholdPageMixin, HouseholdView


class HouseholdPreferencesView(HouseholdPageMixin, UpdateView):
    form_class = HouseholdPreferenceForm
    template_name = "household/preferences.html"
    page_title = "Household preferences"
    success_url = reverse_lazy("household:preferences")

    def get_object(self, queryset=None):
        return HouseholdPreference.for_user(self.request.user)

    def form_valid(self, form):
        messages.success(self.request, "Preferences saved.")
        return super().form_valid(form)


class HelpView(HouseholdView):
    template_name = "household/help.html"
    page_title = "Help"
