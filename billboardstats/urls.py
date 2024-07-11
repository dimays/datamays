from django.urls import path
from . import views

app_name = 'billboardstats'

urlpatterns = [
    path('', views.chart, name='home'),
    path('chart', views.chart, name='chart'),
    path('song', views.song, name='song'),
    path('artist', views.artist, name='artist'),
]