from django.contrib import sitemaps
from django.urls import reverse


class StaticViewSitemap(sitemaps.Sitemap):
    priority = 0.5
    changefreq = "daily"

    def items(self):
        items_list = [
            "home",
            "billboardstats-weekly-chart",
            "billboardstats-song-stats",
            "billboardstats-artist-stats",
        ]
        return items_list

    def location(self, item):
        return reverse(item)