"""
URL configuration for the teams app.
"""
from django.urls import path
from . import views

app_name = "teams"

urlpatterns = [
    path("create/", views.team_create, name="create"),
    path("<int:pk>/", views.team_detail, name="detail"),
    path("join/<str:invite_code>/", views.join_team, name="join"),
]
