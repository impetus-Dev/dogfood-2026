from django.urls import path

from t4.views import (
    CertificateCreateView,
    CertificateDetailView,
    JudgeRecordCreateView,
    PublicKeyView,
    VerifyJudgeRecordView,
)

urlpatterns = [
    path("api/t4/keys/public/", PublicKeyView.as_view(), name="t4_public_key"),
    path("api/t4/judge-records/", JudgeRecordCreateView.as_view(), name="t4_judge_records"),
    path("api/t4/certificates/", CertificateCreateView.as_view(), name="t4_certificates"),
    path("api/t4/certificates/<int:id>/", CertificateDetailView.as_view(), name="t4_certificate_detail"),
    path("api/verify/<str:record_id>/", VerifyJudgeRecordView.as_view(), name="t4_verify_record"),
]
