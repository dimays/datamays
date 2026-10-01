from django import forms

from ..models import BudgetLine, Milestone, Project, ProjectLink, ProjectNote
from .base import StyledFormMixin
from .chores import ChoreForm

DATE = {"type": "date"}


class ProjectForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "summary", "status", "start_on", "target_on", "budget_total"]
        labels = {"start_on": "Start", "target_on": "Target", "budget_total": "Budget ($)"}
        widgets = {
            "summary": forms.Textarea(attrs={"rows": 3}),
            "start_on": forms.DateInput(attrs=DATE, format="%Y-%m-%d"),
            "target_on": forms.DateInput(attrs=DATE, format="%Y-%m-%d"),
            "budget_total": forms.NumberInput(attrs={"step": "0.01", "min": 0, "inputmode": "decimal"}),
        }


class MilestoneForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Milestone
        fields = ["name", "target_on", "completed_on"]
        labels = {"target_on": "Target date", "completed_on": "Done on"}
        widgets = {
            "target_on": forms.DateInput(attrs=DATE, format="%Y-%m-%d"),
            "completed_on": forms.DateInput(attrs=DATE, format="%Y-%m-%d"),
        }


class QuickMilestoneForm(MilestoneForm):
    """The inline "add a milestone" on a project's page: name and date only."""

    class Meta(MilestoneForm.Meta):
        fields = ["name", "target_on"]


class LinkForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ProjectLink
        fields = ["title", "url"]
        labels = {"url": "Link"}
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "e.g. Design board"}),
            "url": forms.URLInput(attrs={"placeholder": "https://docs.google.com/…"}),
        }


class NoteForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ProjectNote
        fields = ["body"]
        labels = {"body": "Add a note or a decision"}
        widgets = {"body": forms.Textarea(attrs={"rows": 2, "placeholder": "e.g. Going with the matte finish."})}


class ProjectTaskForm(ChoreForm):
    """A project task: a household chore, optionally under a milestone.

    Household-only like maintenance — both of you manage a project's tasks —
    with the assignee deciding whose checklist it lands on.
    """

    class Meta(ChoreForm.Meta):
        fields = [*ChoreForm.Meta.fields, "milestone"]

    def __init__(self, *args, project, **kwargs):
        kwargs["household_only"] = True
        super().__init__(*args, **kwargs)
        self.project = project
        # Set before validation, not in save(): Chore.clean() checks the
        # milestone belongs to this project.
        self.instance.project = project
        self.fields["title"].label = "Task"
        self.fields["assignee"].help_text = "Whose checklist it lands on."
        self.fields["milestone"].queryset = project.milestones.all()
        self.fields["milestone"].required = False
        self.fields["milestone"].empty_label = "No milestone"


class BudgetLineForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = BudgetLine
        fields = ["label", "estimated"]
        labels = {"estimated": "Estimate ($)"}
        widgets = {
            "label": forms.TextInput(attrs={"placeholder": "e.g. Tile"}),
            "estimated": forms.NumberInput(attrs={"step": "0.01", "min": 0, "inputmode": "decimal", "placeholder": "0.00"}),
        }
