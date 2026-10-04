from django.http import Http404
from django.views.generic import TemplateView

from .catalog import GAMES, GAMES_BY_SLUG


class GameIndexView(TemplateView):
    """The hub: every game, on the site's own dark theme."""

    template_name = "games/index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["games"] = GAMES
        return context


class GamePlayView(TemplateView):
    """A game's own page.

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
