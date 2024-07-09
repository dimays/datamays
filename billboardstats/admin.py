from django.contrib import admin
from .models import Artist, Song, Chart, ChartSong, ChartArtist, ArtistStats, SongStats

admin.site.register(Artist)
admin.site.register(Song)
admin.site.register(Chart)
admin.site.register(ChartSong)
admin.site.register(ChartArtist)
admin.site.register(ArtistStats)
admin.site.register(SongStats)