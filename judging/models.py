from django.conf import settings
from django.db import models
from events.models import Event
from projects.models import Project


class RubricCriterion(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="rubric_criteria")
    name = models.CharField(max_length=255)
    weight = models.FloatField(default=1.0)

    def __str__(self):
        return f"{self.name} (weight: {self.weight})"


class JudgeAssignment(models.Model):
    judge = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="judge_assignments")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="judge_assignments")

    class Meta:
        unique_together = ("judge", "project")

    def __str__(self):
        return f"Assignment: {self.judge} -> {self.project}"


class Score(models.Model):
    judge = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="scores")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="scores")
    criteria_scores = models.JSONField(default=dict)
    comment = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("judge", "project")

    def __str__(self):
        return f"Score: {self.judge} for {self.project}"
