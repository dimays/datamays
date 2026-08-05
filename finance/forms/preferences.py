"""Per-person display preferences — never household data."""

from django import forms

from ..chart_sections import CHART_SECTION_CHOICES
from ..models import Account, Budget, UserPreference
from ..services.widgets import WIDGET_CHOICES
from .base import StyledFormMixin


def _ordered_for_display(saved, all_slugs):
    """The person's arrangement first, then anything they haven't seen yet.

    Two things at once: slugs retired from the choice list are dropped (a
    stale saved preference must not outlive the section it names, or the
    label lookup below KeyErrors the moment Preferences is opened), and
    newly shipped slugs are appended rather than going missing.
    """
    kept = [slug for slug in saved if slug in all_slugs]
    return kept + [slug for slug in all_slugs if slug not in kept]


def _ordered_for_save(order_field, chosen, all_slugs):
    """What to persist: the drag-and-drop order, filtered to what's ticked.

    Reading the hidden order field rather than the declared choice order is
    what lets a person actually control placement. A missing or corrupted
    value (JS disabled, stale form) falls back to the declared order rather
    than silently dropping every section.
    """
    known = set(all_slugs)
    ordered = [slug for slug in order_field.split(",") if slug in known]

    if not ordered:
        ordered = list(all_slugs)

    return [slug for slug in ordered if slug in chosen]


class PreferencesForm(StyledFormMixin, forms.ModelForm):
    widgets_selected = forms.MultipleChoiceField(
        label="Homepage widgets",
        choices=WIDGET_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )
    # Populated by the drag-and-drop reorder script (finance/js/widget-reorder.js)
    # as a comma-separated slug list reflecting the on-screen row order —
    # every WIDGET_CHOICES slug, not just the checked ones, so unchecking and
    # rechecking a widget doesn't lose its place in the list.
    widget_order = forms.CharField(required=False, widget=forms.HiddenInput())
    chart_sections_selected = forms.MultipleChoiceField(
        label="Charts tab sections",
        choices=CHART_SECTION_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )
    # Same reorder pattern as widget_order, one section down.
    chart_section_order_input = forms.CharField(required=False, widget=forms.HiddenInput())
    accounts_selected = forms.ModelMultipleChoiceField(
        label="Accounts to show",
        queryset=Account.objects.filter(is_active=True),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
        help_text="Leave all unchecked to show every account.",
    )
    budgets_selected = forms.ModelMultipleChoiceField(
        label="Budgets to show",
        queryset=Budget.objects.filter(is_active=True),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
        help_text="Leave all unchecked to show every active budget.",
    )

    class Meta:
        model = UserPreference
        fields = ["recent_transaction_count"]
        widgets = {
            "recent_transaction_count": forms.NumberInput(attrs={"min": 1, "max": 50})
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._widget_slugs = [slug for slug, _ in WIDGET_CHOICES]
        self._section_slugs = [slug for slug, _ in CHART_SECTION_CHOICES]

        if self.instance.pk:
            self.fields["widgets_selected"].initial = self.instance.widgets
            self.fields["accounts_selected"].initial = self.instance.homepage_account_ids
            self.fields["budgets_selected"].initial = self.instance.homepage_budget_ids
            self.fields["chart_sections_selected"].initial = [
                slug for slug in self.instance.chart_section_order
                if slug in self._section_slugs
            ]

            ordered = _ordered_for_display(self.instance.widgets, self._widget_slugs)
            ordered_sections = _ordered_for_display(
                self.instance.chart_section_order, self._section_slugs
            )
        else:
            ordered = self._widget_slugs
            ordered_sections = self._section_slugs

        self.fields["widget_order"].initial = ",".join(ordered)
        self._ordered_slugs = ordered

        self.fields["chart_section_order_input"].initial = ",".join(ordered_sections)
        self._ordered_section_slugs = ordered_sections

    def ordered_widget_rows(self):
        """(slug, label, checked) in the order the reorder UI should render them."""
        checked = set(self.fields["widgets_selected"].initial or [])
        labels = dict(WIDGET_CHOICES)

        return [(slug, labels[slug], slug in checked) for slug in self._ordered_slugs]

    def ordered_chart_section_rows(self):
        """(slug, label, checked) for the Charts tab section reorder UI."""
        checked = set(self.fields["chart_sections_selected"].initial or [])
        labels = dict(CHART_SECTION_CHOICES)

        return [
            (slug, labels[slug], slug in checked) for slug in self._ordered_section_slugs
        ]

    def save(self, commit=True):
        preference = super().save(commit=False)

        preference.homepage_widgets = _ordered_for_save(
            self.cleaned_data["widget_order"],
            set(self.cleaned_data["widgets_selected"]),
            self._widget_slugs,
        )
        preference.chart_sections = _ordered_for_save(
            self.cleaned_data["chart_section_order_input"],
            set(self.cleaned_data["chart_sections_selected"]),
            self._section_slugs,
        )

        preference.homepage_account_ids = [
            account.pk for account in self.cleaned_data["accounts_selected"]
        ]
        preference.homepage_budget_ids = [
            budget.pk for budget in self.cleaned_data["budgets_selected"]
        ]

        if commit:
            preference.save()

        return preference
