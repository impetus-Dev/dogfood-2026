from django.contrib import admin
from .models import Team, TeamMembership


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "event", "invite_code")
    list_filter = ("event",)
    search_fields = ("name", "invite_code")


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    list_display = ("team", "user")
    list_filter = ("team__event",)
    search_fields = ("user__username", "team__name")
