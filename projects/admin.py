from django.contrib import admin
from .models import Project


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("title", "team", "track", "status", "submitted_at")
    list_filter = ("status", "track")
    search_fields = ("title", "summary", "team__name")
