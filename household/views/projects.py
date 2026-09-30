"""The Projects section.

Projects are shared, so both of you manage everything in them (ADR 0011).
Every object is looked up inside a handler or `get_object()`, never in
`dispatch()` — the gate runs there, and a lookup ahead of it would tell a
stranger which ids exist (see docs/architecture.md).
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.functional import cached_property
from django.views import View
from django.views.generic import CreateView, DeleteView, UpdateView

from ..dates import household_today
from ..forms.projects import (
    LinkForm,
    MilestoneForm,
    NoteForm,
    ProjectForm,
    ProjectTaskForm,
    QuickMilestoneForm,
)
from ..models import Chore, Milestone, Project, ProjectLink, ProjectNote
from ..services import occurrences, projects
from .base import HouseholdPageMixin, HouseholdView


def project_url(project):
    return reverse("household:project_detail", args=[project.pk])


class ProjectListView(HouseholdView):
    template_name = "household/projects/list.html"
    page_title = "Projects"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["groups"] = projects.project_list()
        context["today"] = household_today()
        return context


class ProjectCreateView(HouseholdPageMixin, CreateView):
    model = Project
    form_class = ProjectForm
    template_name = "household/projects/form.html"
    page_title = "New project"

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, f"Started “{self.object.name}”. Add milestones and tasks below.")
        return response

    def get_success_url(self):
        return project_url(self.object)


class ProjectUpdateView(HouseholdPageMixin, UpdateView):
    model = Project
    form_class = ProjectForm
    template_name = "household/projects/form.html"

    def get_page_title(self):
        return f"Edit {self.object.name}"

    def get_success_url(self):
        return project_url(self.object)


class ProjectDeleteView(HouseholdPageMixin, DeleteView):
    model = Project
    template_name = "household/projects/confirm_delete.html"
    success_url = reverse_lazy("household:projects")
    page_title = "Delete project"

    def form_valid(self, form):
        messages.success(self.request, f"Deleted “{self.object.name}”.")
        return super().form_valid(form)


class ProjectDetailView(HouseholdView):
    template_name = "household/projects/detail.html"

    @cached_property
    def project(self):
        return get_object_or_404(
            projects.with_progress(Project.objects.all()), pk=self.kwargs["pk"]
        )

    def get_page_title(self):
        return self.project.name

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        project = self.project
        today = household_today()
        open_rows, finished = projects.tasks(project, self.request.user, today)
        entries, undated = projects.timeline(project, today)

        context.update(
            project=project,
            today=today,
            progress=projects.progress(project),
            timeline=entries,
            undated=undated,
            task_rows=open_rows,
            finished_tasks=finished,
            links=project.links.all(),
            notes=project.notes.select_related("author"),
            milestone_form=QuickMilestoneForm(prefix="milestone"),
            link_form=LinkForm(prefix="link"),
            note_form=NoteForm(prefix="note"),
            show_assignee=True,
        )
        return context


class ProjectChildView(HouseholdPageMixin, View):
    """Base for the small POST-only actions on a project's page."""

    http_method_names = ["post"]

    @cached_property
    def project(self):
        return get_object_or_404(Project, pk=self.kwargs["pk"])

    def back(self, anchor=""):
        return redirect(project_url(self.project) + anchor)

    def invalid(self, form, anchor=""):
        first = next(iter(form.errors.values()))[0]
        messages.error(self.request, f"Not saved — {first[0].lower()}{first[1:]}")
        return self.back(anchor)


class MilestoneCreateView(ProjectChildView):
    def post(self, request, pk):
        form = QuickMilestoneForm(request.POST, prefix="milestone")
        if not form.is_valid():
            return self.invalid(form, "#timeline")
        form.instance.project = self.project
        form.save()
        return self.back("#timeline")


class MilestoneToggleView(ProjectChildView):
    """Tick a milestone done today, or untick it."""

    def post(self, request, pk, milestone_pk):
        milestone = get_object_or_404(Milestone, pk=milestone_pk, project=self.project)
        milestone.completed_on = None if milestone.is_done else household_today()
        milestone.save(update_fields=["completed_on", "updated_at"])
        return self.back("#timeline")


class MilestoneUpdateView(HouseholdPageMixin, UpdateView):
    form_class = MilestoneForm
    template_name = "household/projects/milestone_form.html"

    def get_object(self, queryset=None):
        return get_object_or_404(Milestone, pk=self.kwargs["milestone_pk"], project_id=self.kwargs["pk"])

    def get_page_title(self):
        return f"Edit {self.object.name}"

    def get_success_url(self):
        return project_url(self.object.project) + "#timeline"


class MilestoneDeleteView(ProjectChildView):
    def post(self, request, pk, milestone_pk):
        milestone = get_object_or_404(Milestone, pk=milestone_pk, project=self.project)
        # Its tasks stay in the project, just no longer under a milestone.
        milestone.delete()
        messages.success(request, f"Removed the milestone “{milestone.name}”.")
        return self.back("#timeline")


class LinkCreateView(ProjectChildView):
    def post(self, request, pk):
        form = LinkForm(request.POST, prefix="link")
        if not form.is_valid():
            return self.invalid(form, "#links")
        form.instance.project = self.project
        form.save()
        return self.back("#links")


class LinkDeleteView(ProjectChildView):
    def post(self, request, pk, link_pk):
        get_object_or_404(ProjectLink, pk=link_pk, project=self.project).delete()
        return self.back("#links")


class NoteCreateView(ProjectChildView):
    def post(self, request, pk):
        form = NoteForm(request.POST, prefix="note")
        if not form.is_valid():
            return self.invalid(form, "#notes")
        form.instance.project = self.project
        form.instance.author = request.user
        form.save()
        return self.back("#notes")


class NoteDeleteView(ProjectChildView):
    """Only the author removes a note: the log is shared, the words are theirs."""

    def post(self, request, pk, note_pk):
        note = get_object_or_404(ProjectNote, pk=note_pk, project=self.project)
        if note.author_id != request.user.pk:
            raise PermissionDenied
        note.delete()
        return self.back("#notes")


class TaskFormMixin(HouseholdPageMixin):
    template_name = "household/projects/task_form.html"

    @cached_property
    def project(self):
        return get_object_or_404(Project, pk=self.kwargs["pk"])

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update(user=self.request.user, project=self.project)
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["project"] = self.project
        return context

    def get_success_url(self):
        return project_url(self.project) + "#tasks"


class TaskCreateView(TaskFormMixin, CreateView):
    model = Chore
    form_class = ProjectTaskForm
    page_title = "New task"

    def get_initial(self):
        initial = super().get_initial()
        milestone = self.request.GET.get("milestone")
        if milestone and self.project.milestones.filter(pk=milestone).exists():
            initial["milestone"] = milestone
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        occurrences.reschedule(self.object)
        messages.success(self.request, f"Added the task “{self.object.title}”.")
        return response


class TaskUpdateView(TaskFormMixin, UpdateView):
    model = Chore
    form_class = ProjectTaskForm

    def get_object(self, queryset=None):
        return get_object_or_404(Chore, pk=self.kwargs["task_pk"], project=self.project)

    def get_page_title(self):
        return f"Edit {self.object.title}"

    def form_valid(self, form):
        stored = Chore.objects.get(pk=self.object.pk)
        before = (stored.schedule, stored.is_active)
        response = super().form_valid(form)
        if before != (self.object.schedule, self.object.is_active):
            occurrences.reschedule(self.object)
        return response
