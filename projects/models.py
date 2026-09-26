from django.db import models
from events.models import Track


class Project(models.Model):
    team = models.CharField(max_length=255, blank=True, default="")
    track = models.ForeignKey(Track, on_delete=models.SET_NULL, null=True, blank=True, related_name="projects")
    title = models.CharField(max_length=255)
    summary = models.TextField(blank=True, default="")
    repo_url = models.URLField(blank=True, default="")
    status = models.CharField(max_length=50, default="submitted")
    submitted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.title
