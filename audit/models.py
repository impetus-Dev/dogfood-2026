from django.db import models


class AuditEvent(models.Model):
    """
    Immutable audit event record for security-sensitive and operational actions.
    """
    timestamp = models.DateTimeField(auto_now_add=True)
    actor = models.CharField(max_length=255)
    action = models.CharField(max_length=64)
    target = models.CharField(max_length=255)
    metadata = models.JSONField(blank=True, null=True)

    class Meta:
        ordering = ["-timestamp", "-id"]

    def __str__(self):
        return f"[{self.timestamp}] {self.actor} - {self.action} - {self.target}"
