"""Deterministic description-pattern → category rules."""

from django import forms

from ..models import Account, Category, CategoryRule
from .base import StyledFormMixin


class RuleForm(StyledFormMixin, forms.ModelForm):
    """A CategoryRule, editable from Settings rather than only ever created
    sight-unseen via the review queue's "always" checkbox (which only ever
    writes a CONTAINS match on the merchant name). The model already
    supports contains/starts-with/exact/regex matching, optionally scoped
    to one account or an amount range — this just exposes it."""

    class Meta:
        model = CategoryRule
        fields = [
            "pattern", "match_type", "category", "account",
            "min_amount", "max_amount", "priority", "notes",
        ]
        widgets = {
            "pattern": forms.TextInput(attrs={"placeholder": "netflix"}),
            "min_amount": forms.NumberInput(attrs={"step": "0.01"}),
            "max_amount": forms.NumberInput(attrs={"step": "0.01"}),
            "notes": forms.TextInput(),
        }
        help_texts = {
            "pattern": "Matched against the transaction's raw description, case-insensitively.",
            "match_type": "“Contains” is the most forgiving choice when an exact match is unlikely.",
            "account": "Leave unset to apply everywhere.",
            "min_amount": "Signed, inclusive lower bound. Leave blank for no lower bound.",
            "max_amount": "Signed, inclusive upper bound. Leave blank for no upper bound.",
            "priority": "Lower runs first. The first matching rule wins.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.filter(
            is_active=True, children__isnull=True
        ).select_related("parent").alphabetical()
        self.fields["account"].queryset = Account.objects.filter(is_active=True)
        self.fields["account"].required = False
        self.fields["account"].empty_label = "Every account"
        self.fields["min_amount"].required = False
        self.fields["max_amount"].required = False
        self.fields["notes"].required = False
