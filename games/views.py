from django.http import Http404
from django.views.generic import RedirectView, TemplateView

from .catalog import GAMES_BY_SLUG

# The games moved to their own site, with accounts and leaderboards.
NEW_HOME = "https://unnecessaryobstacles.com/"


class GameIndexView(RedirectView):
    """The games hub now lives at unnecessaryobstacles.com."""

    url = NEW_HOME
    permanent = True


class GamePlayView(TemplateView):
    """A game's own page — kept so players can still open their saved cases
    (which live in this site's browser storage) and back them up; the game
    itself tells them it has moved.

    Games do not extend `core/base.html`. Each one sets its own palette and
    wants the whole viewport — the Register is a leather-bound ledger on a
    dark desk, and dropping it inside the site's navbar and footer would
    fight it. The way back to the site is a link the game itself carries.
    """

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        slug = kwargs.get("slug")
        try:
            self.game = GAMES_BY_SLUG[slug]
        except KeyError:
            raise Http404(f"No game named {slug!r}")

    def get_template_names(self):
        return [self.game.template]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["game"] = self.game
        return context
