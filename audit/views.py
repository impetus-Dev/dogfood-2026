"""
API views for the audit trail.
"""
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import AuditEvent
from audit.permissions import IsOrganizer
from audit.serializers import AuditEventSerializer


class AuditListView(APIView):
    """
    GET /api/audit/
    Organizer-only audit trail endpoint.
    Supports optional filtering via query parameter: ?event=<event_id>.
    """
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsOrganizer]

    def get(self, request):
        qs = AuditEvent.objects.all().order_by("-timestamp", "-id")

        event_param = request.query_params.get("event")
        if event_param:
            if event_param.isdigit():
                event_id = int(event_param)
                # Filter by metadata event_id or target starting with event:<id>
                qs = qs.filter(metadata__event_id=event_id)
            else:
                qs = qs.none()

        serializer = AuditEventSerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
