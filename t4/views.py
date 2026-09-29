import base64
from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from t4.models import Certificate, JudgeRecord
from t4.permissions import IsOrganizerOrAdmin
from t4.serializers import (
    CertificateResponseSerializer,
    CreateCertificateSerializer,
    CreateJudgeRecordSerializer,
    JudgeRecordResponseSerializer,
)
from t4.services import (
    generate_certificate,
    generate_judge_record,
    get_public_key,
    get_public_key_base64,
    verify_payload_signature,
)


class PublicKeyView(APIView):
    """
    GET /api/t4/keys/public/
    Public endpoint returning the active Ed25519 public key.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        pub_key = get_public_key()
        pub_key_b64 = get_public_key_base64(pub_key)
        return Response(
            {
                "algorithm": "Ed25519",
                "public_key": pub_key_b64,
            },
            status=status.HTTP_200_OK,
        )


class JudgeRecordCreateView(APIView):
    """
    POST /api/t4/judge-records/
    Organizer/Admin-only endpoint to generate a signed judge participation record.
    """
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsOrganizerOrAdmin]

    def post(self, request):
        serializer = CreateJudgeRecordSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        event = serializer.validated_data["event"]
        judge = serializer.validated_data["judge"]

        try:
            record = generate_judge_record(judge=judge, event=event)
        except ValidationError as e:
            detail = e.messages if hasattr(e, "messages") else [str(e)]
            return Response(
                {"detail": detail[0] if len(detail) == 1 else detail},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = JudgeRecordResponseSerializer(record)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class CertificateCreateView(APIView):
    """
    POST /api/t4/certificates/
    Organizer/Admin-only endpoint to generate a certificate.
    """
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsOrganizerOrAdmin]

    def post(self, request):
        serializer = CreateCertificateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        event = serializer.validated_data["event"]
        user = serializer.validated_data["user"]
        context_type = serializer.validated_data["context_type"]
        project = serializer.validated_data.get("project")

        try:
            cert = generate_certificate(
                event=event,
                user=user,
                project=project,
                context_type=context_type,
            )
        except ValidationError as e:
            detail = e.messages if hasattr(e, "messages") else [str(e)]
            return Response(
                {"detail": detail[0] if len(detail) == 1 else detail},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = CertificateResponseSerializer(cert)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class CertificateDetailView(APIView):
    """
    GET /api/t4/certificates/<id>/
    Public endpoint to retrieve a certificate by ID.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, id):
        try:
            cert = Certificate.objects.get(pk=id)
        except Certificate.DoesNotExist:
            return Response(
                {"detail": "Certificate not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = CertificateResponseSerializer(cert)
        return Response(serializer.data, status=status.HTTP_200_OK)


class VerifyJudgeRecordView(APIView):
    """
    GET /api/verify/<str:record_id>/
    Public verification endpoint using string converter to differentiate
    non-numeric malformed IDs (400) from non-existent numeric IDs (404).
    Always returns HTTP 200 for existing records with valid: true/false.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, record_id):
        # 1. Validate that record_id represents a positive integer
        if not str(record_id).isdigit() or int(record_id) <= 0:
            return Response(
                {"error": "Invalid record ID. Record ID must be a positive integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 2. Look up JudgeRecord
        try:
            record = JudgeRecord.objects.get(pk=int(record_id))
        except JudgeRecord.DoesNotExist:
            return Response(
                {"error": "Judge record not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 3. Perform cryptographic verification
        pub_key = get_public_key()
        pub_key_b64 = get_public_key_base64(pub_key)
        sig_bytes = bytes(record.signature)
        valid = verify_payload_signature(
            record.payload,
            sig_bytes,
            public_key=pub_key,
        )
        sig_b64 = base64.b64encode(sig_bytes).decode("ascii")

        return Response(
            {
                "record_id": record.pk,
                "valid": valid,
                "algorithm": "Ed25519",
                "public_key": pub_key_b64,
                "payload": record.payload,
                "signature": sig_b64,
            },
            status=status.HTTP_200_OK,
        )
