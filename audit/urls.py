"""
URL configuration for the audit app.
"""
from django.urls import path
from audit import views

app_name = "audit"

urlpatterns = [
    path("audit/", views.AuditListView.as_view(), name="audit_list"),
]
