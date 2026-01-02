from django.urls import path
from .views import home, styleguide

urlpatterns = [
    path("", home, name="home"),
    path("styleguide/", styleguide, name="styleguide"),
]
