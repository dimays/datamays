"""The Chores section: checklists, the chore form, and one-tap actions.

Every permission question goes to `services/permissions.py`. The buttons a
person can't use are not drawn, but the endpoints check anyway — the
template is a convenience, the service is the rule.
"""

from itertools import islice
from urllib.parse import urlsplit

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, UpdateView

from .. import scheduling
from ..dates import household_today
from ..forms.chores import SCHEDULE_FIELDS, ChoreForm
from ..forms.maintenance import LogCompletionForm
from ..models import Chore, HouseholdPreference, MaintenanceItem, Occurrence, OccurrenceStatus
from ..redirects import is_safe_path, safe_next
from ..services import checklist, occurrences, permissions
from ..services.members import display_name, partner_of
from .base import HouseholdPageMixin, HouseholdView

UPCOMING_PREVIEW = 3


def is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def page_path(request):
    """The path of the page an htmx request came from, if it is safe."""
    current = urlsplit(request.headers.get("HX-Current-URL", ""))
    path = current.path + (f"?{current.query}" if current.query else "")
    return path if is_safe_path(path) else reverse("household:chores")


class ChecklistView(HouseholdView):
    template_name = "household/chores/checklist.html"
    page_title = "Chores"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        preference = HouseholdPreference.for_user(self.request.user)
        context["preference"] = preference
        context.update(
            checklist.checklist(self.request.user, include_partner=preference.show_partner_chores)
        )
        return context


class ChoreListView(HouseholdView):
    """Every chore, paused ones included — where a paused chore is found again."""

    template_name = "household/chores/all.html"
    page_title = "All chores"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        partner = partner_of(user)
        chores = list(
            occurrences.with_open_occurrence(
                Chore.objects.select_related("owner", "assignee", "maintenance_item")
            )
        )
        # Same rule as every other screen, so this list can't show a chore as
        # overdue that Today shows as due today. Found in review.
        occurrences.refresh(chores, household_today())

        def section(title, rows):
            return {"title": title, "chores": rows}

        context["sections"] = [
            section("Yours", [c for c in chores if c.owner_id == user.pk]),
            section("Shared", [c for c in chores if c.owner_id is None]),
            section(
                f"{display_name(partner)}'s" if partner else "Theirs",
                [c for c in chores if partner and c.owner_id == partner.pk],
            ),
        ]
        context["today"] = household_today()
        return context


class ChoreFormMixin(HouseholdPageMixin):
    model = Chore
    form_class = ChoreForm
    template_name = "household/chores/form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_success_url(self):
        return safe_next(self.request, default=reverse("household:chore_detail", args=[self.object.pk]))


class ChoreCreateView(ChoreFormMixin, CreateView):
    page_title = "New chore"

    def get_initial(self):
        initial = super().get_initial()
        initial["others_can_manage"] = HouseholdPreference.for_user(self.request.user).share_new_chores
        initial["starts_on"] = household_today()
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        occurrences.reschedule(self.object)
        messages.success(self.request, f"Added “{self.object.title}”.")
        return response


class ElsewhereRedirectMixin:
    """Sends a chore to the page that owns it: a maintenance item's chore to
    its Upkeep pages (instructions, supplies, and costs live there), and —
    for editing — a project task to its project's task form.

    Must come *after* the access gate in a view's bases, so it only ever
    runs for a verified member: before the gate, a stranger could tell an
    existing maintenance item (a redirect) from anything else (a 403).
    """

    upkeep_url_name = "household:upkeep_detail"
    # Set on the edit view: a project task is edited in its project, where
    # the milestone choice lives.
    project_task_url_name = None

    def dispatch(self, request, *args, **kwargs):
        item = MaintenanceItem.objects.filter(chore_id=kwargs["pk"]).first()
        if item is not None:
            return redirect(self.upkeep_url_name, item.pk)

        if self.project_task_url_name:
            task = Chore.objects.filter(pk=kwargs["pk"], project__isnull=False).values("project_id").first()
            if task is not None:
                return redirect(self.project_task_url_name, task["project_id"], kwargs["pk"])

        return super().dispatch(request, *args, **kwargs)


class ManagedChoreMixin:
    """Refuses anyone who can't manage the chore. For edit and delete."""

    def get_object(self, queryset=None):
        chore = super().get_object(queryset)
        if not permissions.can_manage(self.request.user, chore):
            raise PermissionDenied
        return chore


class ChoreUpdateView(ManagedChoreMixin, ChoreFormMixin, ElsewhereRedirectMixin, UpdateView):
    upkeep_url_name = "household:upkeep_edit"
    project_task_url_name = "household:project_task_edit"

    def get_page_title(self):
        return f"Edit {self.object.title}"

    @transaction.atomic
    def form_valid(self, form):
        # Read from the database: by now form validation has already copied
        # the new values onto self.object.
        before = Chore.objects.get(pk=self.object.pk)
        response = super().form_valid(form)
        occurrences.apply_edit(self.object, before)
        messages.success(self.request, f"Saved “{self.object.title}”.")
        return response


class ChoreDeleteView(ManagedChoreMixin, HouseholdPageMixin, ElsewhereRedirectMixin, DeleteView):
    upkeep_url_name = "household:upkeep_delete"

    model = Chore
    template_name = "household/chores/confirm_delete.html"
    success_url = reverse_lazy("household:chore_list")
    page_title = "Delete chore"

    def form_valid(self, form):
        messages.success(self.request, f"Deleted “{self.object.title}”.")
        return super().form_valid(form)


class ChoreDetailView(HouseholdPageMixin, ElsewhereRedirectMixin, DetailView):
    model = Chore
    template_name = "household/chores/detail.html"
    context_object_name = "chore"

    def get_queryset(self):
        return Chore.objects.select_related("owner", "assignee", "project", "milestone")

    def get_page_title(self):
        return self.object.title

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        chore = self.object
        user = self.request.user
        today = household_today()

        chore.open_occurrences = list(chore.occurrences.filter(status=OccurrenceStatus.OPEN))
        occurrences.refresh([chore], today)
        rows = checklist.rows_for(user, [chore] if chore.open_occurrences else [], today)

        context.update(
            today=today,
            row=rows[0] if rows else None,
            history=chore.occurrences.exclude(status=OccurrenceStatus.OPEN)
            .select_related("completed_by")
            .order_by("-due_on", "-id")[:20],
            upcoming=self._upcoming(chore, rows[0].occurrence if rows else None),
            can_manage=permissions.can_manage(user, chore),
            owner_name=display_name(chore.owner) if chore.owner else "The household",
        )
        return context

    @staticmethod
    def _upcoming(chore, current):
        """The next few fixed due dates after the current one, to show the pattern."""
        schedule = chore.schedule
        if current is None or current.due_on is None or not schedule.is_fixed:
            return []
        later = (day for day in scheduling.fixed_dates(schedule) if day > current.due_on)
        return list(islice(later, UPCOMING_PREVIEW))


class OccurrenceActionView(HouseholdPageMixin, View):
    """Done, skip, and undo — one tap each, with htmx swapping the row."""

    http_method_names = ["post"]

    CHECKS = {
        "complete": lambda user, occurrence: permissions.can_complete(user, occurrence.chore),
        "skip": lambda user, occurrence: permissions.can_manage(user, occurrence.chore),
        "undo": permissions.can_undo,
    }

    def post(self, request, pk, action):
        if action not in self.CHECKS:
            raise PermissionDenied

        occurrence = get_object_or_404(
            Occurrence.objects.select_related("chore", "chore__owner", "chore__assignee"), pk=pk
        )
        if not self.CHECKS[action](request.user, occurrence):
            raise PermissionDenied

        # Note and cost come from the same small form maintenance uses to log
        # a job, so a cost is validated as money wherever it is posted from.
        details = LogCompletionForm(request.POST)
        if not details.is_valid():
            problem = "That cost doesn't look like an amount" if "cost" in details.errors else "That note is too long"
            messages.error(request, f"{problem} — nothing was changed.")
            return redirect(safe_next(request, default=reverse("household:chores")))
        note = details.cleaned_data["note"].strip()

        if action == "complete":
            following = occurrences.complete(
                occurrence, by=request.user, note=note, cost=details.cleaned_data["cost"]
            )
        elif action == "skip":
            following = occurrences.skip(occurrence, by=request.user, note=note)
        else:
            undone = occurrences.reopen(occurrence)
            following = None

        occurrence.refresh_from_db()
        # Tapped on a row that had already moved on: its date passed and it
        # was recorded as missed (by the sweep, or another screen) while the
        # page sat open. Nothing was done. Found in review: this gave a 500,
        # or a "Marked done" for nothing.
        moved_on = action != "undo" and occurrence.status == OccurrenceStatus.MISSED
        title = occurrence.chore.title

        if not is_htmx(request):
            # A full-page post (maintenance's "Mark done", or no JavaScript)
            # gets no swapped row, so say what happened.
            if moved_on:
                messages.error(request, f"“{title}” {self.moved_on_words(occurrence.chore)} — nothing was changed.")
            elif action == "undo":
                if undone:
                    messages.success(request, f"Undone: “{title}” is back on the list.")
                else:
                    messages.error(request, f"Couldn't undo “{title}” — {self.undo_refusal(occurrence)}.")
            elif occurrence.completed_by_id != request.user.pk:
                who = display_name(occurrence.completed_by)
                messages.error(request, f"“{title}” was already {occurrence.get_status_display().lower()} by {who}.")
            else:
                done = "Marked done" if action == "complete" else "Skipped"
                upcoming = f" — next due {following.due_on:%b} {following.due_on.day}" if following and following.due_on else ""
                messages.success(request, f"{done}: “{title}”{upcoming}.")
            return redirect(safe_next(request, default=reverse("household:chores")))

        today = household_today()
        # The swapped-in row's no-JavaScript fallback should return to the
        # page it sits on, not to this endpoint.
        context = {
            "today": today,
            "next_url": page_path(request),
            # Whether the page showed whose list each row is on (Today does;
            # a person's own checklist doesn't need to) — so the swapped-in
            # row matches the rows around it.
            "show_assignee": request.POST.get("show_assignee") == "1",
        }

        if moved_on:
            # Swap in the row that is open now, if there is one.
            context["announce"] = f"“{title}” {self.moved_on_words(occurrence.chore)} — nothing was changed."
            current = occurrence.chore.occurrences.filter(status=OccurrenceStatus.OPEN).first()
            if current is not None:
                current.chore = occurrence.chore
                occurrence = current

        if occurrence.is_open:
            occurrence.chore.open_occurrences = [occurrence]
            # As the row reads on the page it replaces.
            occurrence.chore.missed_streak = occurrences.missed_streak(occurrence.chore)
            [row] = checklist.rows_for(request.user, [occurrence.chore], today)
            # Announced to screen readers, which otherwise hear nothing when
            # a row is swapped back in.
            context.setdefault("announce", f"“{title}” is back on the list.")
            return render(request, "household/chores/_row.html", {**context, "row": row})
        if action == "undo":
            context["undo_refused"] = self.undo_refusal(occurrence)

        return render(
            request,
            "household/chores/_row_closed.html",
            {**context, "occurrence": occurrence, "following": following,
             # Only a done or skipped one can be undone; a missed row's Undo
             # could never work. Found in review.
             "can_undo": occurrence.status in occurrences.CLOSED_BY_A_PERSON
             and permissions.can_undo(request.user, occurrence)},
        )

    @staticmethod
    def undo_refusal(occurrence):
        if not occurrence.chore.is_active:
            return "it has been paused since"
        return "it has moved on since"

    @staticmethod
    def moved_on_words(chore):
        if not chore.is_active:
            return "has been paused since"
        if not chore.occurrences.filter(status=OccurrenceStatus.OPEN).exists():
            return "has ended since"
        return "had moved on to its next date"


class PartnerToggleView(HouseholdPageMixin, View):
    http_method_names = ["post"]

    def post(self, request):
        preference = HouseholdPreference.for_user(request.user)
        preference.show_partner_chores = not preference.show_partner_chores
        preference.save(update_fields=["show_partner_chores", "updated_at"])
        return redirect(safe_next(request, default=reverse("household:chores")))


class SchedulePreviewView(HouseholdPageMixin, View):
    """The chore form's live "what this means" line, as the fields change."""

    http_method_names = ["get"]

    def get(self, request):
        # The maintenance form prefixes its chore fields ("chore-frequency").
        prefix = request.GET.get("_prefix") or None
        form = ChoreForm(data=request.GET, user=request.user, prefix=prefix)
        form.is_valid()  # runs the schedule validation; unrelated errors are ignored

        errors = [
            message
            for field, field_errors in form.errors.items()
            if field in SCHEDULE_FIELDS or field == "__all__"
            for message in field_errors
        ]
        context = {"errors": errors}

        if not errors:
            schedule = form.instance.schedule
            today = household_today()
            first = scheduling.first_due(schedule, today)
            dates = []
            if first is not None:
                dates = [first]
                if schedule.is_fixed:
                    later = (day for day in scheduling.fixed_dates(schedule) if day > first)
                    dates += list(islice(later, UPCOMING_PREVIEW - 1))
            context.update(words=scheduling.describe(schedule), dates=dates, schedule=schedule, today=today)

        return render(request, "household/chores/_schedule_preview.html", context)
