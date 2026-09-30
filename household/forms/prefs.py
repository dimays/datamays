from django import forms

from ..models import HouseholdPreference
from .base import StyledFormMixin


class HouseholdPreferenceForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = HouseholdPreference
        fields = ["show_partner_chores", "share_new_chores"]
        labels = {
            "show_partner_chores": "Show the other person's chores on Today and the checklist",
            "share_new_chores": "Let the other person manage chores I create, by default",
        }
