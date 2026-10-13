"""What every finance view shares.

Three things kept being restated across the app's view modules:

- the access gate, `HouseholdAccessMixin`
- the header title, `PageTitleMixin`, which used to cost a four-line
  `get_context_data` override on 33 separate views
- "this row belongs to the signed-in person", which alerts and scheduled
  reports each re-expressed in their own querysets

The first two are owned by the household shell (`household/access.py`,
`household/views/base.py`), because every section needs them (ADR 0008). The
third is finance's own.
"""

from django.views.generic import TemplateView

from household.access import HouseholdAccessMixin
from household.views.base import PageTitleMixin


class FinancePageMixin(PageTitleMixin, HouseholdAccessMixin):
    """Both halves, for any page behind the full gate — almost everything."""


class FinanceView(FinancePageMixin, TemplateView):
    """Base for every plain finance page: gated, with a title for the header."""


class PersonalQuerysetMixin:
    """Scopes a view to rows belonging to the signed-in person.

    Alerts and scheduled reports are personal — each person sets their own
    thresholds and gets mail at their own address — so neither should ever
    surface, edit, or delete the other's. This is the half that every
    personal view needs, whatever it does with the row once it has it.
    """

    def get_queryset(self):
        return super().get_queryset().filter(user=self.request.user)


class PersonalObjectMixin(PersonalQuerysetMixin):
    """The above, plus stamping the owner when a row is created.

    Deliberately separate from the scoping half. A DeleteView is confirmed
    with a plain `Form` that has no `.instance`, so a mixin that assumed one
    turned every delete into a 500 — which is what the first version of this
    did, and what `AlertDeleteView` now proves it doesn't.

    So: use `PersonalQuerysetMixin` for anything that reads or deletes, and
    this for anything that writes a new row.
    """

    def form_valid(self, form):
        form.instance.user = self.request.user
        return super().form_valid(form)
