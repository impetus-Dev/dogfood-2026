"""
URL configuration for core app (dashboard).
"""

from django.urls import path
from .views import dashboard_view

urlpatterns = [
    path("dashboard/", dashboard_view, name="dashboard"),
    path("dashboard", dashboard_view, name="dashboard_noslash"),
]
