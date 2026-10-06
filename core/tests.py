from django.test import SimpleTestCase


class GamesMovedTests(SimpleTestCase):
    """The games live at unnecessaryobstacles.com now; old links follow them."""

    def test_the_games_hub_redirects_to_the_new_site(self):
        r = self.client.get("/games/")
        self.assertRedirects(r, "https://unnecessaryobstacles.com/", status_code=301, fetch_redirect_response=False)

    def test_an_old_game_link_lands_on_the_same_game(self):
        r = self.client.get("/games/the-register/")
        self.assertRedirects(r, "https://unnecessaryobstacles.com/games/the-register/", status_code=301, fetch_redirect_response=False)
