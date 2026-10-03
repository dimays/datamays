"""What every private page shares, in every section.

The access gate and the header title. Finance's own view base builds on these
(`finance/views/base.py`), so a finance page and a household page are gated
and titled the same way.
"""

from django.views.generic import TemplateView

from ..access import HouseholdAccessMixin


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


class HouseholdPageMixin(PageTitleMixin, HouseholdAccessMixin):
    """Both halves, for any page behind the full gate — almost everything."""


class HouseholdView(HouseholdPageMixin, TemplateView):
    """Base for every plain household page: gated, with a title for the header."""
