"""The CSV upload step of the import wizard."""

from django import forms

from ..models import Account, Institution, RecordType
from .base import StyledFormMixin


class UploadForm(StyledFormMixin, forms.Form):
    institution = forms.ModelChoiceField(
        queryset=Institution.objects.filter(is_active=True),
    )
    account = forms.ModelChoiceField(
        queryset=Account.objects.filter(is_active=True),
        required=False,
        help_text="Required for transactions and balances.",
    )
    record_type = forms.ChoiceField(choices=RecordType.choices)
    csv_file = forms.FileField(
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"})
    )

    def clean(self):
        cleaned = super().clean()

        if cleaned.get("record_type") in {RecordType.TRANSACTIONS, RecordType.BALANCES} and not cleaned.get("account"):
            raise forms.ValidationError(
                "Pick the account these rows belong to — transactions and "
                "balances cannot be filed without one."
            )

        return cleaned
