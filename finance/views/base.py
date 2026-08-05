"""What every finance view shares.

Three things kept being restated across the app's view modules, and all three
live here now:

- the access gate (`FinanceAccessMixin`, from `finance/access.py`)
- the header title, which used to cost a four-line `get_context_data`
  override on 33 separate views
- "this row belongs to the signed-in person", which alerts and scheduled
  reports each re-expressed in their own querysets
"""

from django.views.generic import TemplateView

from ..access import FinanceAccessMixin


class PageTitleMixin:
    """The title the header renders — and nothing else.

    Set `page_title` for a fixed title; override `get_page_title()` when it
    depends on the object being edited ("Edit Groceries"). Both beat the
    `get_context_data` override this replaces, which was four lines of
    ceremony around a single string.

    `setdefault` rather than assignment: a view that computes the title
    alongside other context in its own `get_context_data` still wins.

    Deliberately separate from the access gate below. The TOTP setup and
    verify screens need a title but must *not* require a cleared second
    factor — they are how you clear it — so they mix in this half alone.
    """

    page_title = ""

    def get_page_title(self):
        return self.page_title

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("page_title", self.get_page_title())
        return context


class FinancePageMixin(PageTitleMixin, FinanceAccessMixin):
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
