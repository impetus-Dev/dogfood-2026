from django import forms
from django.core.exceptions import ValidationError
from .models import Project
from teams.models import Team, TeamMembership
from events.models import Track


class ProjectForm(forms.ModelForm):
    """
    ModelForm for project creation.
    Validates title, summary, repo_url, team, track, and cross-event invariant.
    """
    class Meta:
        model = Project
        fields = ["title", "summary", "repo_url", "team", "track"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user and user.is_authenticated:
            self.fields["team"].queryset = Team.objects.filter(memberships__user=user)
        else:
            self.fields["team"].queryset = Team.objects.none()

    def clean(self):
        cleaned_data = super().clean()
        team = cleaned_data.get("team")
        track = cleaned_data.get("track")

        if team and self.user and self.user.is_authenticated:
            if not TeamMembership.objects.filter(team=team, user=self.user).exists():
                self.add_error("team", "You must be a member of the selected team to create a project.")

        if team and track:
            if team.event_id != track.event_id:
                self.add_error(None, "Project team and track must belong to the same event.")

        return cleaned_data


class ProjectEditForm(forms.ModelForm):
    """
    ModelForm for editing draft projects.
    Allows editing title, summary, repo_url, and track (within same event).
    Does NOT allow modifying team, status, or submitted_at directly.
    """
    class Meta:
        model = Project
        fields = ["title", "summary", "repo_url", "track"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and getattr(self.instance, "team", None):
            self.fields["track"].queryset = Track.objects.filter(event=self.instance.team.event)

    def clean(self):
        cleaned_data = super().clean()
        if self.instance and self.instance.status != "draft":
            self.add_error(None, "Submitted projects cannot be edited.")

        track = cleaned_data.get("track")
        if track and self.instance and getattr(self.instance, "team", None):
            if self.instance.team.event_id != track.event_id:
                self.add_error("track", "Project team and track must belong to the same event.")

        return cleaned_data
