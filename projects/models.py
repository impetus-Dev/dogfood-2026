from django.db import models
from teams.models import Team
from events.models import Track


class Project(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("submitted", "Submitted"),
    ]

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="projects")
    track = models.ForeignKey(Track, on_delete=models.CASCADE, related_name="projects")
    title = models.CharField(max_length=255)
    summary = models.TextField()
    repo_url = models.URLField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="draft")
    submitted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.title
