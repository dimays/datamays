"""The Chores section: checklists, the chore form, and one-tap actions.

Every permission question goes to `services/permissions.py`. The buttons a
person can't use are not drawn, but the endpoints check anyway — the
template is a convenience, the service is the rule.
"""

from itertools import islice
from urllib.parse import urlsplit

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, UpdateView

from .. import scheduling
from ..dates import household_today
from ..forms.chores import SCHEDULE_FIELDS, ChoreForm
from ..models import Chore, HouseholdPreference, Occurrence, OccurrenceStatus
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
            occurrences.with_open_occurrence(Chore.objects.select_related("owner", "assignee"))
        )

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


class ManagedChoreMixin:
    """Refuses anyone who can't manage the chore. For edit and delete."""

    def get_object(self, queryset=None):
        chore = super().get_object(queryset)
        if not permissions.can_manage(self.request.user, chore):
            raise PermissionDenied
        return chore


class ChoreUpdateView(ManagedChoreMixin, ChoreFormMixin, UpdateView):
    def get_page_title(self):
        return f"Edit {self.object.title}"

    def form_valid(self, form):
        # Read from the database: by now form validation has already copied
        # the new values onto self.object.
        stored = Chore.objects.get(pk=self.object.pk)
        before = (stored.schedule, stored.is_active)
        response = super().form_valid(form)

        # Only a schedule change replaces the open occurrence. Doing it on
        # every save would quietly reset an overdue chore whose title was
        # merely tidied up.
        if before != (self.object.schedule, self.object.is_active):
            occurrences.reschedule(self.object)

        messages.success(self.request, f"Saved “{self.object.title}”.")
        return response


class ChoreDeleteView(ManagedChoreMixin, HouseholdPageMixin, DeleteView):
    model = Chore
    template_name = "household/chores/confirm_delete.html"
    success_url = reverse_lazy("household:chore_list")
    page_title = "Delete chore"

    def form_valid(self, form):
        messages.success(self.request, f"Deleted “{self.object.title}”.")
        return super().form_valid(form)


class ChoreDetailView(HouseholdPageMixin, DetailView):
    model = Chore
    template_name = "household/chores/detail.html"
    context_object_name = "chore"

    def get_queryset(self):
        return Chore.objects.select_related("owner", "assignee")

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

        note = request.POST.get("note", "").strip()[:1000]
        if action == "complete":
            following = occurrences.complete(occurrence, by=request.user, note=note)
        elif action == "skip":
            following = occurrences.skip(occurrence, by=request.user, note=note)
        else:
            occurrences.reopen(occurrence)
            following = None

        if not is_htmx(request):
            return redirect(safe_next(request, default=reverse("household:chores")))

        occurrence.refresh_from_db()
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

        if occurrence.is_open:
            occurrence.chore.open_occurrences = [occurrence]
            [row] = checklist.rows_for(request.user, [occurrence.chore], today)
            return render(request, "household/chores/_row.html", {**context, "row": row})

        return render(
            request,
            "household/chores/_row_closed.html",
            {**context, "occurrence": occurrence, "following": following,
             "can_undo": permissions.can_undo(request.user, occurrence)},
        )


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
        form = ChoreForm(data=request.GET, user=request.user)
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
