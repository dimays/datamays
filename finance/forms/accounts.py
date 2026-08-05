"""Accounts, and the one-off manual balance reading."""

from django import forms

from ..models import Account, Institution
from .base import StyledFormMixin


class BalanceUpdateForm(StyledFormMixin, forms.Form):
    """A one-off balance reading, typed in by hand — the lightweight
    alternative to a full CSV balances import for a single account.

    Deliberately a plain Form, not a ModelForm: saving it does more than set
    two fields on the Account (see AccountUpdateView._update_balance), it also
    records an AccountBalanceSnapshot so the reading feeds the same balance
    history charts a sync or CSV import would.
    """

    as_of = forms.DateField(
        label="Balance as of",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    current_balance = forms.DecimalField(
        label="Balance",
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"step": "0.01"}),
        help_text="Signed the same way it reads everywhere else in the app — negative for a debt.",
    )
    available_balance = forms.DecimalField(
        label="Available balance",
        max_digits=12,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={"step": "0.01"}),
    )


class AccountForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Account
        fields = [
            "name", "account_type", "owner", "mask", "debt_reported_positive",
            "is_active", "include_in_net_worth", "include_in_spending",
            "sort_order", "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


class ManualAccountForm(StyledFormMixin, forms.ModelForm):
    """For an account with no connection — the mortgage, the 401(k), anything
    only ever kept current by a CSV import or by hand. A connected account's
    institution is set by the sync that discovered it, so this form (and its
    institution field) is create-only; editing an existing account goes
    through AccountForm instead."""

    class Meta:
        model = Account
        fields = [
            "institution", "name", "account_type", "owner", "mask",
            "current_balance", "balance_as_of",
            "debt_reported_positive", "include_in_net_worth", "include_in_spending",
            "notes",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "401(k)"}),
            "current_balance": forms.NumberInput(attrs={"step": "0.01"}),
            "balance_as_of": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }
        help_texts = {
            "current_balance": "Optional — leave blank and set it later with a CSV "
            "balance import if you don't have a figure handy right now.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["institution"].queryset = Institution.objects.filter(is_active=True)
        self.fields["current_balance"].required = False
        self.fields["balance_as_of"].required = False
