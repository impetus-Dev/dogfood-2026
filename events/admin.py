from django.contrib import admin
from .models import Event, Track


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("name", "submissions_close", "voting_close", "voting_mode")
    list_filter = ("voting_mode",)
    search_fields = ("name",)


@admin.register(Track)
class TrackAdmin(admin.ModelAdmin):
    list_display = ("name", "event")
    list_filter = ("event",)
    search_fields = ("name", "event__name")
