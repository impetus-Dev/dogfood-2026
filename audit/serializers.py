"""
Serializers for AuditEvent.
"""
from rest_framework import serializers

from audit.models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for AuditEvent records.
    """

    class Meta:
        model = AuditEvent
        fields = ["id", "timestamp", "actor", "action", "target", "metadata"]
        read_only_fields = fields
