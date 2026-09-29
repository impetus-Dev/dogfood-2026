from django.urls import path

from t4.embed_views import embed_gallery_view, embed_script_view
from t4.views import (
    BulkExportView,
    BulkImportView,
    CertificateCreateView,
    CertificateDetailView,
    JudgeRecordCreateView,
    OpenAPISchemaView,
    PublicKeyView,
    VerifyJudgeRecordView,
)

urlpatterns = [
    path("embed/gallery.js", embed_script_view, name="embed_gallery_js"),
    path("embed/gallery/<str:event_id>/", embed_gallery_view, name="embed_gallery"),
    path("embed/gallery/<str:event_id>", embed_gallery_view),
    path("api/t4/keys/public/", PublicKeyView.as_view(), name="t4_public_key"),
    path("api/t4/judge-records/", JudgeRecordCreateView.as_view(), name="t4_judge_records"),
    path("api/t4/certificates/", CertificateCreateView.as_view(), name="t4_certificates"),
    path("api/t4/certificates/<int:id>/", CertificateDetailView.as_view(), name="t4_certificate_detail"),
    path("api/verify/<str:record_id>/", VerifyJudgeRecordView.as_view(), name="t4_verify_record"),
    # Bulk Export endpoints
    path("api/export/bulk/", BulkExportView.as_view(), name="bulk_export"),
    path("api/export/bulk", BulkExportView.as_view(), name="bulk_export_noslash"),
    path("api/t4/export/", BulkExportView.as_view(), name="t4_bulk_export"),
    path("api/t4/export", BulkExportView.as_view(), name="t4_bulk_export_noslash"),
    # Bulk Import endpoints
    path("api/import/bulk/", BulkImportView.as_view(), name="bulk_import"),
    path("api/import/bulk", BulkImportView.as_view(), name="bulk_import_noslash"),
    path("api/t4/import/", BulkImportView.as_view(), name="t4_bulk_import"),
    path("api/t4/import", BulkImportView.as_view(), name="t4_bulk_import_noslash"),
    # OpenAPI Schema endpoints
    path("api/schema/", OpenAPISchemaView.as_view(), name="openapi_schema"),
    path("api/schema", OpenAPISchemaView.as_view(), name="openapi_schema_noslash"),
    path("api/openapi.json", OpenAPISchemaView.as_view(), name="openapi_json"),
]
