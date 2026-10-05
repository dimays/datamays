"""The games on the site, declared in code rather than stored in the database.

A game is a fixed thing: a page that ships with the deploy, plus a card on the
hub. Nothing about one is user-generated and nothing about one changes between
deploys, so a table would buy a migration, an admin screen and a query per
page load in exchange for nothing. `Project` is in the database because its
copy gets edited without a deploy; a game's does not.

Adding a game is three files and one entry here:

    games/templates/games/<slug>.html         the game itself
    games/templates/games/thumbs/<slug>.html  the card's artwork
    an entry in GAMES below

A game too big for one template keeps its scripts and styles under
games/static/games/<slug>/ and loads them from its page.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Game:
    slug: str
    title: str
    tagline: str
    description: str
    template: str
    thumbnail: str
    tags: tuple[str, ...]
    year: int

    @property
    def url(self) -> str:
        from django.urls import reverse

        return reverse("games:play", kwargs={"slug": self.slug})


GAMES = (
    Game(
        slug="the-register",
        title="The Register",
        tagline="A murder mystery in 26,000 to 52,000 names.",
        description=(
            "Somewhere in a register of tens of thousands of people — a liner's "
            "manifest, a mining-town census, a festival's wristband list — is "
            "a killer. You have a handful of clues, each a small puzzle of its "
            "own. Strike out everyone they clear until one name is left. Every "
            "case is generated fresh, leans on its own mix of evidence, and is "
            "checked to have exactly one answer. A fan game inspired by Iris "
            "Starling's The Killer Isn't Alice."
        ),
        template="games/the-register.html",
        thumbnail="games/thumbs/the-register.html",
        tags=("Logic", "Mystery", "Printable", "Saves in your browser"),
        year=2026,
    ),
)

GAMES_BY_SLUG = {game.slug: game for game in GAMES}
