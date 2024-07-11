from django.urls import path
from . import views

app_name = 'bio'

urlpatterns = [
    path('', views.home, name='home'),
]