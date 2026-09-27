"""
URL configuration for the accounts app.
"""
from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("whoami/", views.whoami, name="whoami"),
]
