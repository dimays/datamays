from django.db import models


class Artist(models.Model):
    id = models.BigAutoField(
        primary_key=True,
        db_comment='Primary key representing a unique artist'
        )
    name = models.CharField(
        max_length=200,
        db_comment='Name of the artist as listed on the Billboard Hot 100'
        )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_comment='Time (in UTC) at which this record was created'
        )
    updated_at = models.DateTimeField(
        auto_now=True,
        db_comment='Time (in UTC) at which this record was most recently updated'
        )
    
    class Meta:
        db_table = 'artists'
        db_table_comment = 'A record for each unique artist'
        ordering = ['id']
    
    def __str__(self):
        str_rep = self.name
        return str_rep
    

class Song(models.Model):
    id = models.BigAutoField(
        primary_key=True,
        db_comment='Primary key representing a unique song'
        )
    artist = models.ForeignKey(
        Artist,
        on_delete=models.CASCADE,
        related_name='song_artist_ids',
        db_comment='Foreign key, references artists.id, represents the artist credited for this song on the Hot 100'
        )
    title = models.CharField(
        max_length=500,
        db_comment='Title of the song'
        )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_comment='Time (in UTC) at which this record was created'
        )
    updated_at = models.DateTimeField(
        auto_now=True,
        db_comment='Time (in UTC) at which this record was most recently updated'
        )
    
    class Meta:
        db_table = 'songs'
        db_table_comment = 'A record for each unique song'
        ordering = ['id']
    
    def __str__(self):
        str_rep = f"'{self.title}' by {self.artist.name}"
        return str_rep


class Chart(models.Model):
    id = models.BigAutoField(
        primary_key=True,
        db_comment='Primary key representing a unique Weekly Hot 100 chart'
        )
    chart_date = models.DateField(
        db_comment='Release date of the chart'
        )
    start_date = models.DateField(
        db_comment='Start date of the period for this chart'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_comment='Time (in UTC) at which this record was created'
        )
    updated_at = models.DateTimeField(
        auto_now=True,
        db_comment='Time (in UTC) at which this record was most recently updated'
        )
    
    class Meta:
        db_table = 'charts'
        db_table_comment = 'A record for each Weekly Hot 100 chart'
        ordering = ['-chart_date']
    
    def __str__(self):
        str_rep = f"Chart on {self.chart_date}"
        return str_rep


class ChartSong(models.Model):
    id = models.BigAutoField(
        primary_key=True,
        db_comment='Primary key representing a unique song on each Weekly Hot 100 chart'
        )
    song = models.ForeignKey(
        Song,
        on_delete=models.PROTECT,
        related_name='chart_song_song_ids',
        db_comment='Foreign key, references songs.id, represents the song'
        )
    chart = models.ForeignKey(
        Chart,
        on_delete=models.PROTECT,
        related_name='chart_song_chart_ids',
        db_comment='Foreign key, references charts.id, represents the chart this song appears on'
        )
    position = models.SmallIntegerField(
        db_comment='Represents the position of this song on this weekly chart'
        )
    last_week_position = models.SmallIntegerField(
        blank=True,
        null=True,
        default=None,
        db_comment='The position of this song on the previous weekly chart (NULL if new song this week)'
        )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_comment='Time (in UTC) at which this record was created'
        )
    updated_at = models.DateTimeField(
        auto_now=True,
        db_comment='Time (in UTC) at which this record was most recently updated'
        )
    
    class Meta:
        db_table = 'chart_songs'
        db_table_comment = 'A record for each song on each Weekly Hot 100 chart'
        ordering = ['id']
    
    def __str__(self):
        str_rep = f"{self.song.__str__} (#{self.position} on {self.chart.chart_date})"
        return str_rep
    

class ChartArtist(models.Model):
    id = models.BigAutoField(
        primary_key=True,
        db_comment='Primary key representing a unique artist on each Weekly Hot 100 chart'
        )
    artist = models.ForeignKey(
        Artist,
        on_delete=models.PROTECT,
        related_name='chart_artist_artist_ids',
        db_comment='Foreign key, references artists.id, represents the artist'
        )
    chart = models.ForeignKey(
        Chart,
        on_delete=models.PROTECT,
        related_name='chart_artist_chart_ids',
        db_comment='Foreign key, references charts.id, represents the chart this song appears on'
        )
    peak_position = models.IntegerField(
        db_comment='Represents the peak position of this artist on this weekly chart'
        )
    num_songs_on_chart = models.IntegerField(
        db_comment='Represents the number of songs this artist had on this weekly chart'
        )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_comment='Time (in UTC) at which this record was created'
        )
    updated_at = models.DateTimeField(
        auto_now=True,
        db_comment='Time (in UTC) at which this record was most recently updated'
        )

    class Meta:
        db_table = 'chart_artists'
        db_table_comment = 'A record for each song on each Weekly Hot 100 chart'
        ordering = ['id']
    
    def __str__(self):
        str_rep = f"{self.artist.name} (#{self.peak_position} on {self.chart.chart_date})"
        return str_rep


class ArtistStats(models.Model):
    id = models.BigAutoField(
        primary_key=True,
        db_comment='Primary key representing the current stats for each artist'
        )
    artist = models.ForeignKey(
        Artist,
        on_delete=models.PROTECT,
        related_name='artist_stats_artist_ids',
        db_comment='Foreign key, references artists.id, represents the song'
        )
    peak_position = models.IntegerField(
        db_comment='Represents the peak position of this artist from any given week'
        )
    num_songs_at_one = models.IntegerField(
        db_comment='Represents the distinct count of #1 songs this artist has ever had'
        )
    num_songs_on_chart = models.IntegerField(
        db_comment='Represents the distinct count of songs this artist has ever had on the Hot 100 Charts'
        )
    num_weeks_at_one = models.IntegerField(
        db_comment='Represents the distinct number of weeks this artist had a song at #1'
        )
    num_weeks_on_chart = models.IntegerField(
        db_comment='Represents the distinct number of weeks this artist had a song on the Hot 100 Charts'
        )
    on_chart_from = models.DateField(
        db_comment='Represents the first date this artist appeared on the Hot 100 Charts'
        )
    on_chart_to = models.DateField(
        db_comment='Represents the most recent date this artist appeared on the Hot 100 Charts'
        )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_comment='Time (in UTC) at which this record was created'
        )
    updated_at = models.DateTimeField(
        auto_now=True,
        db_comment='Time (in UTC) at which this record was most recently updated'
        )

    class Meta:
        db_table = 'artist_stats'
        db_table_comment = 'A record for each artist, with fields representing various overall stats'
        ordering = ['id']
    
    def __str__(self):
        str_rep = f"{self.artist.name} (Hot 100 Artist from {self.on_chart_from} to {self.on_chart_to})"
        return str_rep
    

class SongStats(models.Model):
    id = models.BigAutoField(
        primary_key=True,
        db_comment='Primary key representing the current stats for each song'
        )
    song = models.ForeignKey(
        Song,
        on_delete=models.PROTECT,
        related_name='song_stats_song_ids',
        db_comment='Foreign key, references songs.id, represents the song'
        )
    peak_position = models.IntegerField(
        db_comment='Represents the peak position of this song from any given week'
        )
    entry_position = models.IntegerField(
        db_comment='Represents the earliest position of this song from any given week'
        )
    final_position = models.IntegerField(
        db_comment='Represents the most recent position of this song from any given week'
        )
    num_weeks_at_one = models.IntegerField(
        db_comment='Represents the distinct number of weeks this song was at #1'
        )
    num_weeks_on_chart = models.IntegerField(
        db_comment='Represents the distinct number of weeks this song appeared on the Hot 100 Charts'
        )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_comment='Time (in UTC) at which this record was created'
        )
    updated_at = models.DateTimeField(
        auto_now=True,
        db_comment='Time (in UTC) at which this record was most recently updated'
        )

    class Meta:
        db_table = 'song_stats'
        db_table_comment = 'A record for each song, with fields representing various overall stats'
        ordering = ['id']
    
    def __str__(self):
        str_rep = f"{self.song.name}"
        return str_rep
