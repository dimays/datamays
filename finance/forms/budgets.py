"""Budgets — an amount, a reset cycle, and what counts toward it."""

from django import forms

from ..dates import household_today
from ..models import Account, Budget, Category, CategoryKind
from .base import StyledFormMixin


class BudgetForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Budget
        fields = [
            "name", "amount", "period_type", "anchor_date",
            "categories", "accounts", "rollover", "is_active", "notes",
        ]
        widgets = {
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "anchor_date": forms.DateInput(attrs={"type": "date"}),
            "categories": forms.CheckboxSelectMultiple(),
            "accounts": forms.CheckboxSelectMultiple(),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }
        help_texts = {
            "anchor_date": "Sets when the cycle resets — pick a payday for a pay-cycle budget.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Transfers and income are never spending, so offering them here would
        # only produce budgets that can never be met.
        self.fields["categories"].queryset = Category.objects.filter(
            is_active=True, kind=CategoryKind.EXPENSE
        ).select_related("parent").alphabetical()

        self.fields["accounts"].queryset = Account.objects.filter(is_active=True)
        self.fields["accounts"].required = False
        self.fields["categories"].required = True

        if not self.instance.pk:
            self.fields["anchor_date"].initial = household_today().replace(day=1)
