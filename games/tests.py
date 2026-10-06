from django.test import SimpleTestCase
from django.urls import reverse

from .catalog import GAMES, GAMES_BY_SLUG


class GameIndexTests(SimpleTestCase):
    def test_the_hub_has_moved_to_its_own_site(self):
        response = self.client.get(reverse("games:index"))
        self.assertRedirects(response, "https://unnecessaryobstacles.com/", status_code=301, fetch_redirect_response=False)


class GamePlayTests(SimpleTestCase):
    def test_every_catalog_entry_renders(self):
        """The catalog names templates by string, so a typo in one would only
        surface when somebody clicked the card. Render them all instead."""
        for game in GAMES:
            with self.subTest(game=game.slug):
                response = self.client.get(game.url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, game.title)

    def test_the_register_tells_players_it_has_moved(self):
        response = self.client.get(GAMES_BY_SLUG["the-register"].url)
        self.assertContains(response, 'data-moved="https://unnecessaryobstacles.com/games/the-register/"')

    def test_unknown_game_is_404(self):
        response = self.client.get("/games/tic-tac-toe/")
        self.assertEqual(response.status_code, 404)


class CatalogTests(SimpleTestCase):
    def test_slugs_are_unique(self):
        self.assertEqual(len(GAMES_BY_SLUG), len(GAMES))


class TheRegisterTests(SimpleTestCase):
    def test_page_runs_the_app_from_browser_storage(self):
        """Without data-storage="browser" the app would try to reach the local
        server it uses on a desktop, and fail on every save."""
        response = self.client.get(GAMES_BY_SLUG["the-register"].url)
        self.assertContains(response, 'data-storage="browser"')
        self.assertContains(response, "games/the-register/app.js")

    def test_app_files_are_published(self):
        """The app is copied in by the Register's tools/publish-site.sh; a page
        whose scripts were never copied would load to a blank screen."""
        from django.contrib.staticfiles import finders

        for path in ("app.js", "styles.css", "site.webmanifest", "js/store.js", "engine/worker.js"):
            with self.subTest(path=path):
                self.assertIsNotNone(finders.find(f"games/the-register/{path}"))
