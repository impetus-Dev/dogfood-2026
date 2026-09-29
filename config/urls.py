"""
URL configuration for DOGFOOD 2026 hackathon platform.
"""
from django.contrib import admin
from django.urls import include, path
from projects.views import project_gallery, project_create

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('teams/', include('teams.urls')),
    path('projects', project_gallery, name='gallery_noslash'),
    path('projects/new', project_create, name='project_create_noslash'),
    path('projects/submit', project_create, name='project_submit_noslash'),
    path('projects/', include('projects.urls')),
    path('api/', include('voting.urls')),
    path('api/', include('audit.urls')),
    path('', include('judging.urls')),
    path('', include('t4.urls')),
]
