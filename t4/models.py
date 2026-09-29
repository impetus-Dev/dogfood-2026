from django.conf import settings
from django.db import models
from events.models import Event


class Certificate(models.Model):
    recipient_name = models.CharField(max_length=255)
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="certificates",
    )
    role_or_project = models.CharField(max_length=255)
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-issued_at", "-id"]

    def __str__(self):
        return f"Certificate: {self.recipient_name} - {self.role_or_project} ({self.event.name})"


class JudgeRecord(models.Model):
    judge = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="judge_records",
    )
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="judge_records",
    )
    payload = models.JSONField()
    signature = models.BinaryField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"JudgeRecord: {self.judge} - {self.event.name} ({self.pk})"
