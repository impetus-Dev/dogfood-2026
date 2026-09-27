from django.db import models
from django.contrib.auth.models import User
from events.models import Event


class Team(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="teams")
    name = models.CharField(max_length=255)
    invite_code = models.CharField(max_length=64, unique=True)
    external_id = models.CharField(max_length=64, blank=True, null=True, unique=True)

    def __str__(self):
        return self.name


class TeamMembership(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="team_memberships")

    class Meta:
        unique_together = ("team", "user")

    def __str__(self):
        return f"{self.user.username} in {self.team.name}"
