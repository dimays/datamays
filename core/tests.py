import json
import re

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from .models import Post, Project


class GamesMovedTests(SimpleTestCase):
    """The games live at unnecessaryobstacles.com now; old links follow them."""

    def test_the_games_hub_redirects_to_the_new_site(self):
        r = self.client.get("/games/")
        self.assertRedirects(r, "https://unnecessaryobstacles.com/", status_code=301, fetch_redirect_response=False)

    def test_an_old_game_link_lands_on_the_same_game(self):
        r = self.client.get("/games/the-register/")
        self.assertRedirects(r, "https://unnecessaryobstacles.com/games/the-register/", status_code=301, fetch_redirect_response=False)



def ld_json(html):
    """The structured data on a page, parsed."""
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    return json.loads(match.group(1)) if match else None


class SearchMetadataTests(TestCase):
    """Every public page names its one canonical address and says what it is."""

    def setUp(self):
        self.post = Post.objects.create(
            title='Tables, "quotes" and </script>',
            slug="a-post",
            summary="What this post is about.",
            content="Some words.",
            published_at=timezone.now(),
        )
        self.draft = Post.objects.create(title="Draft", slug="a-draft", summary="Not yet.", content="Soon.")
        self.project = Project.objects.create(
            title="A project", slug="a-project", short_description="One line about it.",
            blog_post_slug="a-draft",
        )
        self.hidden = Project.objects.create(title="Hidden", slug="hidden", short_description="Shh.", is_public=False)

    def test_canonical_is_on_www_whatever_host_asked(self):
        r = self.client.get("/projects/", HTTP_HOST="datamays-ba2d010703db.herokuapp.com")
        self.assertContains(r, '<link rel="canonical" href="https://www.datamays.com/projects/" />', html=False)

    def test_canonical_keeps_only_the_page_number(self):
        r = self.client.get("/writing/?page=1&utm_source=x")
        self.assertContains(r, 'href="https://www.datamays.com/writing/" />')

    def test_a_page_has_a_description_and_a_preview_card(self):
        r = self.client.get("/projects/a-project/")
        self.assertContains(r, "<title>A project — David Mays</title>")
        self.assertContains(r, '<meta name="description" content="One line about it." />')
        self.assertContains(r, 'property="og:image" content="https://www.datamays.com/static/img/og/datamays')
        self.assertContains(r, '<meta name="twitter:card" content="summary_large_image" />')

    def test_a_post_is_a_blog_posting_and_cant_break_out_of_its_script(self):
        r = self.client.get("/writing/a-post/")
        self.assertNotContains(r, "</script>\"")
        data = ld_json(r.content.decode())
        posting = data["@graph"][0]
        self.assertEqual(posting["@type"], "BlogPosting")
        self.assertEqual(posting["headline"], 'Tables, "quotes" and </script>')
        self.assertEqual(posting["url"], "https://www.datamays.com/writing/a-post/")
        self.assertEqual(posting["author"]["name"], "David Mays")
        self.assertIn("datePublished", posting)

    def test_the_home_page_says_who_and_what(self):
        types = {thing["@type"] for thing in ld_json(self.client.get("/").content.decode())["@graph"]}
        self.assertEqual(types, {"Person", "WebSite"})

    def test_a_drafts_write_up_isnt_linked_until_its_published(self):
        self.assertNotContains(self.client.get("/projects/a-project/"), "/writing/a-draft/")
        self.draft.published_at = timezone.now()
        self.draft.save()
        self.assertContains(self.client.get("/projects/a-project/"), "/writing/a-draft/")

    def test_a_hidden_project_is_a_404_to_everyone_but_staff(self):
        self.assertEqual(self.client.get("/projects/hidden/").status_code, 404)

    def test_the_sitemap_lists_public_pages_on_www_only(self):
        body = self.client.get("/sitemap.xml", HTTP_HOST="datamays.com").content.decode()
        self.assertIn("<loc>https://www.datamays.com/</loc>", body)
        self.assertIn("<loc>https://www.datamays.com/projects/a-project/</loc>", body)
        self.assertIn("<loc>https://www.datamays.com/writing/a-post/</loc>", body)
        self.assertNotIn("a-draft", body)
        self.assertNotIn("/projects/hidden/", body)
        self.assertNotIn("/finance", body)
        self.assertNotIn("/household", body)

    def test_robots_points_at_the_sitemap_and_names_no_private_paths(self):
        body = self.client.get("/robots.txt").content.decode()
        self.assertIn("Sitemap: https://www.datamays.com/sitemap.xml", body)
        self.assertNotIn("finance", body)
        self.assertNotIn("household", body)

    def test_a_404_asks_not_to_be_indexed(self):
        self.assertContains(self.client.get("/writing/a-draft/"), 'content="noindex"', status_code=404)


class UnnecessaryObstaclesContentTests(TestCase):
    """The migration's project page and draft post (core/migrations/0006)."""

    def test_the_project_is_public_and_the_post_is_a_draft(self):
        project = Project.objects.get(slug="unnecessary-obstacles")
        self.assertTrue(project.is_public)
        self.assertIn("<h3", project.overview_html)
        self.assertIsNone(Post.objects.get(slug="building-unnecessary-obstacles-with-claude-code").published_at)

    def test_the_project_page_links_to_the_games_in_words(self):
        r = self.client.get("/projects/unnecessary-obstacles/")
        self.assertContains(r, '<a href="https://unnecessaryobstacles.com/guide/">The technical guide</a>', html=True)
        self.assertContains(r, '<a href="https://unnecessaryobstacles.com/games/contract-rummy/">Contract Rummy</a>', html=True)
        self.assertContains(r, "Visit Unnecessary Obstacles")
        self.assertContains(r, 'content="https://unnecessaryobstacles.com/static/img/og/site.png"')
        # The draft isn't linked yet.
        self.assertNotContains(r, "/writing/building-unnecessary-obstacles-with-claude-code/")
