from django import forms

from ..models import MaintenanceItem
from .base import StyledFormMixin


class MaintenanceItemForm(StyledFormMixin, forms.ModelForm):
    """The item's own details. Its name and schedule are the chore's, edited
    alongside with `ChoreForm(household_only=True)`."""

    class Meta:
        model = MaintenanceItem
        fields = ["area", "location", "instructions", "supplies", "supply_url", "estimated_cost"]
        labels = {
            "supply_url": "Where to buy supplies",
            "estimated_cost": "Usual cost ($)",
        }
        widgets = {
            "instructions": forms.Textarea(attrs={"rows": 4}),
            "supplies": forms.Textarea(attrs={"rows": 2}),
            "estimated_cost": forms.NumberInput(attrs={"step": "0.01", "min": 0, "inputmode": "decimal"}),
        }


class LogCompletionForm(StyledFormMixin, forms.Form):
    """Marking maintenance done, with what it cost and anything worth noting."""

    cost = forms.DecimalField(
        required=False,
        min_value=0,
        max_digits=14,
        decimal_places=2,
        label="What it cost ($)",
        widget=forms.NumberInput(attrs={"step": "0.01", "min": 0, "inputmode": "decimal"}),
    )
    note = forms.CharField(
        required=False,
        max_length=1000,
        label="Note",
        widget=forms.TextInput(attrs={"placeholder": "e.g. used the MERV 13 this time"}),
    )
