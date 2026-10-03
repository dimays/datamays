"""The Upkeep section: shared home maintenance.

Maintenance is household work, so both of you manage every item (ADR 0011);
there is no per-item permission to check. Each item's name and schedule are
its chore's, edited here alongside the item's own details.
"""

from itertools import islice

from django.contrib import messages
from django.db import transaction
from django.db.models import F
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.utils.functional import cached_property
from django.views.generic import DeleteView, TemplateView

from .. import scheduling
from ..dates import household_today
from ..forms.chores import ChoreForm
from ..forms.maintenance import LogCompletionForm, MaintenanceItemForm
from ..maintenance_library import BY_KEY
from ..models import Chore, MaintenanceItem, Occurrence, OccurrenceStatus
from ..services import checklist, maintenance, occurrences, spending
from .base import HouseholdPageMixin, HouseholdView

UPCOMING_PREVIEW = 3


class UpkeepListView(HouseholdView):
    template_name = "household/upkeep/list.html"
    page_title = "Upkeep"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        overview = maintenance.overview()
        context.update(overview)
        items = [item for _, area_items in overview["areas"] for item in area_items]
        context["costs"] = [
            spending.projected_costs(items, overview["today"], days) for days in (90, 365)
        ]
        context["library_count"] = len(maintenance.available_library_entries())
        return context


class UpkeepFormView(HouseholdPageMixin, TemplateView):
    """Create or edit an item: its chore (name, schedule, whose list) and its
    details (area, instructions, supplies, cost), saved together."""

    template_name = "household/upkeep/form.html"
    item = None

    def get_forms(self, data=None):
        chore = self.item.chore if self.item else None
        initial = None if chore else {"starts_on": household_today(), "frequency": scheduling.Frequency.YEARLY}
        return (
            ChoreForm(data, instance=chore, initial=initial, user=self.request.user,
                      household_only=True, prefix="chore"),
            MaintenanceItemForm(data, instance=self.item, prefix="item"),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if "chore_form" not in kwargs:
            context["chore_form"], context["item_form"] = self.get_forms()
        context["item"] = self.item
        return context

    def post(self, request, *args, **kwargs):
        chore_form, item_form = self.get_forms(request.POST)
        if not (chore_form.is_valid() and item_form.is_valid()):
            return self.render_to_response(
                self.get_context_data(chore_form=chore_form, item_form=item_form)
            )

        before = Chore.objects.get(pk=self.item.chore_id) if self.item else None

        with transaction.atomic():
            chore = chore_form.save()
            item = item_form.save(commit=False)
            item.chore = chore
            item.save()

            if before is None:
                occurrences.reschedule(chore)
            else:
                occurrences.apply_edit(chore, before)

        messages.success(request, f"Saved “{chore.title}”.")
        return redirect("household:upkeep_detail", item.pk)


class UpkeepCreateView(UpkeepFormView):
    page_title = "New upkeep item"


class UpkeepUpdateView(UpkeepFormView):
    # Looked up lazily, never in dispatch(): the gate runs in dispatch, and a
    # lookup ahead of it would answer a stranger with 404 for a missing item
    # and 403 for a real one — telling them which ids exist.
    @cached_property
    def item(self):
        return get_object_or_404(MaintenanceItem.objects.select_related("chore"), pk=self.kwargs["pk"])

    def get_page_title(self):
        return f"Edit {self.item.name}"


class UpkeepDetailView(HouseholdView):
    template_name = "household/upkeep/detail.html"

    @cached_property
    def item(self):
        # Lazily, after the gate — see UpkeepUpdateView.item.
        return get_object_or_404(
            MaintenanceItem.objects.select_related("chore", "chore__assignee"), pk=self.kwargs["pk"]
        )

    def get_page_title(self):
        return self.item.name

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        item, chore = self.item, self.item.chore
        today = household_today()

        chore.open_occurrences = list(chore.occurrences.filter(status=OccurrenceStatus.OPEN))
        occurrences.refresh([chore], today)
        rows = checklist.rows_for(self.request.user, [chore] if chore.open_occurrences else [], today)
        row = rows[0] if rows else None

        upcoming = []
        if row and row.occurrence.due_on and chore.schedule.is_fixed:
            later = (day for day in scheduling.fixed_dates(chore.schedule) if day > row.occurrence.due_on)
            upcoming = list(islice(later, UPCOMING_PREVIEW))

        context.update(
            item=item,
            chore=chore,
            today=today,
            row=row,
            upcoming=upcoming,
            log_form=LogCompletionForm(initial={"cost": item.estimated_cost}),
            history=chore.occurrences.exclude(status=OccurrenceStatus.OPEN)
            .select_related("completed_by", "transaction")
            # Done jobs first, newest first. Missed rows have no completion
            # time, and Postgres sorts NULLs first on a descending order —
            # found in review: a year of misses pushed every job (and its
            # cost) out of the twenty.
            .order_by(F("completed_at").desc(nulls_last=True), "-due_on", "-id")[:20],
            cost_by_year=maintenance.cost_by_year(item),
        )
        return context


class UpkeepDeleteView(HouseholdPageMixin, DeleteView):
    """Deleting an item deletes its chore, and so its history, too."""

    model = MaintenanceItem
    template_name = "household/upkeep/confirm_delete.html"
    success_url = reverse_lazy("household:upkeep")
    page_title = "Delete upkeep item"

    def form_valid(self, form):
        name = self.object.name
        self.object.chore.delete()  # cascades to the item and the history
        messages.success(self.request, f"Deleted “{name}”.")
        return redirect(self.success_url)


class LibraryView(HouseholdView):
    template_name = "household/upkeep/library.html"
    page_title = "Starter list"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["entries"] = maintenance.available_library_entries()
        return context


class LibraryAdoptView(HouseholdPageMixin, View):
    http_method_names = ["post"]

    def post(self, request, key):
        if key not in BY_KEY:
            raise Http404
        if key not in {entry.key for entry in maintenance.available_library_entries()}:
            messages.info(request, "That one is already on your list.")
            return redirect("household:upkeep_library")

        item = maintenance.adopt(key)
        messages.success(
            request,
            f"Added “{item.name}” — {item.chore.describe_schedule().lower()}. "
            "Edit it to set whose list it lands on, the location, or the supplies.",
        )
        return redirect(reverse("household:upkeep_library"))


class JobLinkView(HouseholdView):
    """Tie a done maintenance job to the purchase behind it."""

    template_name = "household/upkeep/link.html"
    page_title = "Link a purchase"

    @cached_property
    def occurrence(self):
        return get_object_or_404(
            Occurrence.objects.select_related("chore", "transaction"),
            pk=self.kwargs["occurrence_pk"],
            chore__maintenance_item__pk=self.kwargs["pk"],
            status=OccurrenceStatus.DONE,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = self.request.GET.get("q", "").strip()[:100]
        context.update(
            item_pk=self.kwargs["pk"],
            occurrence=self.occurrence,
            query=query,
            candidates=spending.job_candidates(self.occurrence, household_today(), query),
        )
        return context

    def post(self, request, pk, occurrence_pk):
        if request.POST.get("unlink"):
            spending.unlink_job(self.occurrence)
            messages.success(request, "Unlinked the purchase.")
        elif spending.link_job(self.occurrence, request.POST.get("transaction")):
            cost = self.occurrence.cost
            messages.success(request, "Linked the purchase." + (f" The cost is now ${cost:,.2f}." if cost is not None else ""))
        else:
            messages.error(
                request,
                "That can't be linked — it isn't a purchase finance counts as spending, "
                "it's a refund, or it's already the purchase behind another job.",
            )
        return redirect("household:upkeep_detail", pk)
