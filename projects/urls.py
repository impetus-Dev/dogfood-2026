"""
URL configuration for the projects app.
"""
from django.urls import path, re_path
from . import views

app_name = "projects"

urlpatterns = [
    re_path(r"^new/?$", views.project_create, name="create"),
    path("<int:pk>/", views.project_detail, name="detail"),
    re_path(r"^(?P<pk>\d+)/edit/?$", views.project_edit, name="edit"),
    re_path(r"^(?P<pk>\d+)/submit/?$", views.project_submit, name="submit"),
]
