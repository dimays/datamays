"""Creating and editing a chore, schedule included."""

from dataclasses import replace

from django import forms

from ..models import Chore
from .. import scheduling
from ..dates import household_today
from ..scheduling import Anchor, Frequency, WEEKDAY_NAMES
from ..services.members import display_name, members
from .base import StyledFormMixin

PERSONAL = "personal"
HOUSEHOLD = "household"

# Cleared unless the frequency uses them, so a value left behind in a field
# the form has hidden (weekdays picked, then frequency switched to monthly)
# can't fail validation for a reason the person can no longer see.
ONLY_WHEN_REPEATING = [
    "interval", "weekdays", "monthly_mode", "anchor", "ends_on",
    "max_occurrences", "deadline_offset_days", "season_start_month", "season_end_month",
]

SCHEDULE_FIELDS = ["frequency", "starts_on", *ONLY_WHEN_REPEATING, "deadline"]


class ChoreForm(StyledFormMixin, forms.ModelForm):
    whose = forms.ChoiceField(
        label="Whose chore",
        widget=forms.RadioSelect,
        help_text="A shared chore is household work either of you can manage.",
    )
    assignee = forms.ModelChoiceField(
        queryset=None,
        required=False,
        empty_label="Either of us",
        label="On whose list",
        help_text="Shared chores only.",
    )
    weekdays = forms.TypedMultipleChoiceField(
        choices=list(enumerate(WEEKDAY_NAMES)),
        coerce=int,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="On",
        help_text="Leave empty to repeat on the first due date's weekday.",
    )

    class Meta:
        model = Chore
        fields = [
            "title", "notes", "assignee", "others_can_manage",
            "frequency", "starts_on", "interval", "weekdays", "monthly_mode", "anchor",
            "ends_on", "max_occurrences", "deadline", "deadline_offset_days",
            "season_start_month", "season_end_month", "is_active",
        ]
        labels = {
            "starts_on": "Due",
            "interval": "Every",
            "anchor": "How it repeats",
            "ends_on": "Ends on",
            "max_occurrences": "Or after this many times",
            "deadline_offset_days": "Days to finish",
            "season_start_month": "Only from",
            "season_end_month": "Through",
            "others_can_manage": "Let the other person manage this chore",
            "is_active": "Active",
        }
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
            "starts_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "ends_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "deadline": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "interval": forms.NumberInput(attrs={"min": 1, "inputmode": "numeric"}),
            "max_occurrences": forms.NumberInput(attrs={"min": 1, "inputmode": "numeric"}),
            "deadline_offset_days": forms.NumberInput(attrs={"min": 0, "inputmode": "numeric"}),
            "anchor": forms.RadioSelect,
        }

    def __init__(self, *args, user, household_only=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.household_only = household_only

        # A shared chore has no owner; offering to make it personal makes it yours.
        owner = (self.instance.owner if self.instance.pk else None) or user
        self.fields["whose"].choices = [
            (PERSONAL, f"{display_name(owner)}'s" if owner != user else "Mine"),
            (HOUSEHOLD, "Shared household chore"),
        ]
        if self.instance.pk:
            self.fields["whose"].initial = HOUSEHOLD if self.instance.is_household_owned else PERSONAL
        else:
            self.fields["whose"].initial = PERSONAL

        # The form shows and hides fields as these change (Alpine, in
        # chores/form.html); the server-side clean() is what actually decides.
        self.fields["whose"].widget.attrs["x-model"] = "whose"
        self.fields["frequency"].widget.attrs["x-model"] = "frequency"
        self.fields["anchor"].widget.attrs["x-model"] = "anchor"

        self.fields["assignee"].queryset = members()
        self.fields["assignee"].label_from_instance = display_name
        self.fields["anchor"].choices = Anchor.choices

        # Only the owner decides whose a personal chore is. The grant lets the
        # other person manage it, not take it over: switching it to shared
        # and back would have made them its owner. Found in review.
        if (
            not household_only
            and self.instance.pk
            and self.instance.owner_id
            and self.instance.owner_id != user.pk
        ):
            self.fields["whose"].disabled = True
            self.fields["whose"].help_text = "Only its owner can change whose chore this is."

        # Maintenance is shared work by definition (ADR 0011): no "whose",
        # no grant — both of you manage it, and it can sit on either list.
        if household_only:
            del self.fields["whose"]
            del self.fields["others_can_manage"]
            self.fields["title"].label = "Name"
            self.fields["assignee"].help_text = "Whose list it lands on when it's due."

    def clean(self):
        cleaned = super().clean()

        if cleaned.get("frequency") == Frequency.ONCE:
            cleaned["interval"] = 1
            cleaned["anchor"] = Anchor.FIXED
            for name in ["weekdays", "ends_on", "max_occurrences", "deadline_offset_days",
                         "season_start_month", "season_end_month"]:
                cleaned[name] = [] if name == "weekdays" else None
        else:
            cleaned["deadline"] = None
            if cleaned.get("frequency") != Frequency.WEEKLY or cleaned.get("anchor") == Anchor.AFTER_COMPLETION:
                cleaned["weekdays"] = []

        self._check_dates_left(cleaned)

        if self.household_only:
            cleaned["whose"] = HOUSEHOLD
        elif cleaned.get("whose") == PERSONAL:
            cleaned["assignee"] = None  # set to the owner in save()

        return cleaned

    def save(self, commit=True):
        chore = super().save(commit=False)

        if self.cleaned_data["whose"] == HOUSEHOLD:
            chore.owner = None
            chore.others_can_manage = False  # shared work is already shared
        else:
            chore.owner = chore.owner if (self.instance.pk and chore.owner_id) else self.user
            chore.assignee = chore.owner

        if commit:
            chore.save()
        return chore


    def _check_dates_left(self, cleaned):
        """Refuse a schedule with nothing left to do from today.

        Found in review: an end date or count already used up was accepted,
        and the chore silently appeared on no list. Only checked for a new
        chore or a changed schedule — a finished series whose title is being
        tidied up is fine as it is.
        """
        if cleaned.get("frequency") in (None, Frequency.ONCE) or not cleaned.get("starts_on"):
            return

        fields = {name: cleaned.get(name) for name in SCHEDULE_FIELDS if name != "deadline"}
        fields["weekdays"] = fields.get("weekdays") or []
        proposed = Chore(**{k: v for k, v in fields.items() if v is not None or k in ("ends_on", "max_occurrences")})
        today = household_today()
        new = replace(proposed.schedule, counts_from=today)
        if self.instance.pk and replace(self.instance.schedule, counts_from=today) == new:
            return
        # A schedule refused for another reason (the model's validation,
        # which runs after this) would only gain a misleading second error.
        if self.errors or scheduling.validate(new):
            return

        if not new.is_fixed:
            # After-completion: the count restarts with the change, so only
            # an end date already past leaves nothing to do.
            if new.ends_on and new.ends_on < today:
                self.add_error("ends_on", "That end date has already passed.")
            return

        if scheduling.first_fixed_on_or_after(new, max(today, new.starts_on)) is None:
            self.add_error(
                "ends_on",
                "That schedule has no dates left from today — check the end date, the count, or the season.",
            )
