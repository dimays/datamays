"""
URL configuration for datamays project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.views.generic import RedirectView

handler403 = "datamays.views.permission_denied"

urlpatterns = [
    path('admin/', admin.site.urls),
    path("", include("core.urls")),
    path("contact/", include("contact.urls")),
    path("finance/", include("finance.urls")),
    # The games moved to their own site, unnecessaryobstacles.com: the hub
    # to its home page, and any old game link to the same page there.
    path("games/", RedirectView.as_view(url="https://unnecessaryobstacles.com/", permanent=True)),
    re_path(r"^games/(?P<rest>.+)$", RedirectView.as_view(url="https://unnecessaryobstacles.com/games/%(rest)s", permanent=True)),
]
