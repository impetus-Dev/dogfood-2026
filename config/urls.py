"""
URL configuration for DOGFOOD 2026 hackathon platform.
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('teams/', include('teams.urls')),
    path('projects/', include('projects.urls')),
]
