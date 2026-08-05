"""Institutions — the banks, brokerages and lenders accounts belong to."""

from django import forms
from django.utils.text import slugify

from ..models import Institution
from .base import StyledFormMixin


class InstitutionForm(StyledFormMixin, forms.ModelForm):
    """Every institution goes through here, whether it ends up connected via
    SimpleFIN or only ever fed by hand-uploaded statements — CSV import and
    manual accounts both need an Institution to attach to, and until now the
    only way to create one was the side effect of connecting a SimpleFIN
    integration."""

    class Meta:
        model = Institution
        fields = ["name", "provider", "owner", "website", "notes", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Northwestern Mutual"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "provider": "How data from here normally arrives — SimpleFIN connects "
            "automatically; CSV/manual means you'll keep it current by hand.",
        }

    def save(self, commit=True):
        institution = super().save(commit=False)

        if not institution.slug:
            institution.slug = slugify(institution.name)[:140]

        if commit:
            institution.save()

        return institution
