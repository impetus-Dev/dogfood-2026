import base64
import json
import os
import shutil
import tempfile
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import Profile
from events.models import Event, Track
from judging.models import JudgeAssignment, Score
from projects.models import Project
from teams.models import Team, TeamMembership
from t4.models import Certificate, JudgeRecord
from t4.services import (
    canonicalize_payload,
    generate_certificate,
    generate_judge_record,
    get_public_key,
    get_public_key_base64,
    init_signing_key,
    sign_payload,
    verify_payload_signature,
)

User = get_user_model()


class T4BaseTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.temp_dir = tempfile.mkdtemp()
        self.key_path = os.path.join(self.temp_dir, "test_signing_key")
        self.settings_override = self.settings(T4_SIGNING_KEY_PATH=self.key_path)
        self.settings_override.enable()
        init_signing_key(self.key_path)

        # Base event
        self.event = Event.objects.create(
            name="Dogfood Hackathon 2026",
            submissions_close=timezone.now() + timezone.timedelta(days=2),
            voting_mode="authenticated",
        )
        self.other_event = Event.objects.create(
            name="Other Event",
            submissions_close=timezone.now() + timezone.timedelta(days=2),
            voting_mode="authenticated",
        )

        self.track = Track.objects.create(
            event=self.event,
            name="Main Track",
        )
        self.other_track = Track.objects.create(
            event=self.other_event,
            name="Other Track",
        )

        # Users & profiles
        self.organizer = User.objects.create_user(
            username="org_user", password="password123"
        )
        Profile.objects.create(user=self.organizer, role="organizer")

        self.admin = User.objects.create_user(
            username="admin_user", password="password123"
        )
        Profile.objects.create(user=self.admin, role="admin")

        self.participant = User.objects.create_user(
            username="part_user",
            first_name="Alice",
            last_name="Participant",
            password="password123",
        )
        Profile.objects.create(user=self.participant, role="participant")

        self.other_participant = User.objects.create_user(
            username="unrelated_user", password="password123"
        )
        Profile.objects.create(user=self.other_participant, role="participant")

        self.judge = User.objects.create_user(
            username="judge_user",
            first_name="Bob",
            last_name="Judge",
            password="password123",
        )
        Profile.objects.create(user=self.judge, role="judge")

        self.non_participating_judge = User.objects.create_user(
            username="idle_judge", password="password123"
        )
        Profile.objects.create(user=self.non_participating_judge, role="judge")

        # Team & Project
        self.team = Team.objects.create(
            event=self.event,
            name="Team Alpha",
            invite_code="alpha123",
        )
        TeamMembership.objects.create(team=self.team, user=self.participant)

        self.project = Project.objects.create(
            team=self.team,
            track=self.track,
            title="Awesome Project",
            summary="A revolutionary hackathon project.",
            repo_url="https://github.com/example/awesome",
            status="submitted",
        )

        # Judging evidence
        JudgeAssignment.objects.create(judge=self.judge, project=self.project)
        Score.objects.create(
            judge=self.judge,
            project=self.project,
            criteria_scores={"quality": 9},
            comment="Great work",
        )

        self.client = APIClient()

    def tearDown(self):
        self.settings_override.disable()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        super().tearDown()


class CanonicalizationAndCryptographyTests(T4BaseTestCase):
    def test_canonical_payload_is_deterministic(self):
        payload1 = {"b": 2, "a": 1, "c": [3, 2, 1]}
        payload2 = {"c": [3, 2, 1], "a": 1, "b": 2}
        bytes1 = canonicalize_payload(payload1)
        bytes2 = canonicalize_payload(payload2)
        self.assertEqual(bytes1, bytes2)
        self.assertEqual(bytes1, b'{"a":1,"b":2,"c":[3,2,1]}')

    def test_ed25519_sign_and_verify_roundtrip(self):
        payload = {"record": "test", "id": 123}
        sig = sign_payload(payload, path=self.key_path)
        self.assertIsInstance(sig, bytes)
        self.assertEqual(len(sig), 64)

        valid = verify_payload_signature(payload, sig, path=self.key_path)
        self.assertTrue(valid)

    def test_modified_payload_fails_verification(self):
        payload = {"record": "test", "id": 123}
        sig = sign_payload(payload, path=self.key_path)
        tampered_payload = {"record": "test", "id": 124}
        valid = verify_payload_signature(tampered_payload, sig, path=self.key_path)
        self.assertFalse(valid)

    def test_modified_signature_fails_verification(self):
        payload = {"record": "test", "id": 123}
        sig = sign_payload(payload, path=self.key_path)
        tampered_sig = bytes([sig[0] ^ 0xFF]) + sig[1:]
        valid = verify_payload_signature(payload, tampered_sig, path=self.key_path)
        self.assertFalse(valid)

    def test_unexpected_runtime_error_in_verify_payload_signature_propagates(self):
        payload = {"record": "test", "id": 123}
        sig = sign_payload(payload, path=self.key_path)

        # 1. Internal key-loading failure must propagate, NOT return False
        with patch("t4.services.get_public_key", side_effect=RuntimeError("Key storage failure")):
            with self.assertRaises(RuntimeError):
                verify_payload_signature(payload, sig)

        # 2. Unexpected error during verification must propagate, NOT return False
        class ExplodingPublicKey:
            def verify(self, signature, data):
                raise RuntimeError("Cryptographic subsystem failure")

        with self.assertRaises(RuntimeError):
            verify_payload_signature(payload, sig, public_key=ExplodingPublicKey())



class PublicKeyAPITests(T4BaseTestCase):
    def test_public_key_endpoint_success(self):
        resp = self.client.get("/api/t4/keys/public/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data.get("algorithm"), "Ed25519")
        pub_key_b64 = resp.data.get("public_key")
        self.assertTrue(bool(pub_key_b64))

        # Two calls must return the same public key
        resp2 = self.client.get("/api/t4/keys/public/")
        self.assertEqual(resp2.data.get("public_key"), pub_key_b64)

        # Base64 decodes to exactly 32 bytes
        decoded = base64.b64decode(pub_key_b64)
        self.assertEqual(len(decoded), 32)


class CertificateGenerationAndAPITests(T4BaseTestCase):
    def test_valid_participant_certificate_with_project(self):
        cert = generate_certificate(
            event=self.event,
            user=self.participant,
            project=self.project,
            context_type="participant",
        )
        self.assertEqual(cert.recipient_name, "Alice Participant")
        self.assertEqual(cert.role_or_project, "Participant - Awesome Project")
        self.assertEqual(cert.event, self.event)

    def test_valid_participant_certificate_without_project(self):
        cert = generate_certificate(
            event=self.event,
            user=self.participant,
            project=None,
            context_type="participant",
        )
        self.assertEqual(cert.recipient_name, "Alice Participant")
        self.assertEqual(cert.role_or_project, "Participant - Team Alpha")

    def test_valid_judge_certificate(self):
        cert = generate_certificate(
            event=self.event,
            user=self.judge,
            context_type="judge",
        )
        self.assertEqual(cert.recipient_name, "Bob Judge")
        self.assertEqual(cert.role_or_project, "Judge - Participation")

    def test_organizer_can_generate_certificate_via_api(self):
        self.client.force_authenticate(user=self.organizer)
        resp = self.client.post(
            "/api/t4/certificates/",
            {
                "event": self.event.pk,
                "context_type": "participant",
                "user": self.participant.pk,
                "project": self.project.pk,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["recipient_name"], "Alice Participant")
        self.assertEqual(resp.data["role_or_project"], "Participant - Awesome Project")
        self.assertEqual(resp.data["event"], self.event.pk)
        self.assertIn("id", resp.data)
        self.assertIn("issued_at", resp.data)

    def test_admin_can_generate_certificate_via_api(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            "/api/t4/certificates/",
            {
                "event": self.event.pk,
                "context_type": "judge",
                "user": self.judge.pk,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["recipient_name"], "Bob Judge")

    def test_anonymous_post_certificate_returns_401_or_403(self):
        # Must never return 500
        resp = self.client.post(
            "/api/t4/certificates/",
            {
                "event": self.event.pk,
                "context_type": "participant",
                "user": self.participant.pk,
            },
            format="json",
        )
        self.assertIn(resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_participant_cannot_generate_certificate(self):
        self.client.force_authenticate(user=self.participant)
        resp = self.client.post(
            "/api/t4/certificates/",
            {
                "event": self.event.pk,
                "context_type": "participant",
                "user": self.participant.pk,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_event_returns_400(self):
        self.client.force_authenticate(user=self.organizer)
        resp = self.client.post(
            "/api/t4/certificates/",
            {
                "context_type": "participant",
                "user": self.participant.pk,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_integer_event_returns_400(self):
        self.client.force_authenticate(user=self.organizer)
        resp = self.client.post(
            "/api/t4/certificates/",
            {
                "event": "abc",
                "context_type": "participant",
                "user": self.participant.pk,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_user_returns_400(self):
        self.client.force_authenticate(user=self.organizer)
        resp = self.client.post(
            "/api/t4/certificates/",
            {
                "event": self.event.pk,
                "context_type": "participant",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bad_participant_event_relationship_returns_400(self):
        self.client.force_authenticate(user=self.organizer)
        # other_participant is not in any team in self.event
        resp = self.client.post(
            "/api/t4/certificates/",
            {
                "event": self.event.pk,
                "context_type": "participant",
                "user": self.other_participant.pk,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bad_project_event_relationship_returns_400(self):
        other_team = Team.objects.create(event=self.other_event, name="Other", invite_code="other123")
        other_proj = Project.objects.create(
            team=other_team,
            track=self.other_track,
            title="Other",
            summary="Other",
            repo_url="https://github.com/example/other",
        )
        self.client.force_authenticate(user=self.organizer)
        resp = self.client.post(
            "/api/t4/certificates/",
            {
                "event": self.event.pk,
                "context_type": "participant",
                "user": self.participant.pk,
                "project": other_proj.pk,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bad_judge_role_returns_400(self):
        self.client.force_authenticate(user=self.organizer)
        # participant user used with judge context
        resp = self.client.post(
            "/api/t4/certificates/",
            {
                "event": self.event.pk,
                "context_type": "judge",
                "user": self.participant.pk,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_public_certificate_retrieval(self):
        cert = generate_certificate(
            event=self.event,
            user=self.participant,
            project=self.project,
            context_type="participant",
        )
        resp = self.client.get(f"/api/t4/certificates/{cert.pk}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["id"], cert.pk)
        self.assertEqual(resp.data["recipient_name"], "Alice Participant")
        self.assertEqual(resp.data["role_or_project"], "Participant - Awesome Project")
        self.assertEqual(resp.data["event"], self.event.pk)
        # Never expose private details
        self.assertNotIn("password", resp.data)
        self.assertNotIn("email", resp.data)

    def test_missing_certificate_returns_404(self):
        resp = self.client.get("/api/t4/certificates/999999/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_unexpected_exception_in_certificate_post_propagates_not_400(self):
        self.client.force_authenticate(user=self.organizer)
        with patch("t4.views.generate_certificate", side_effect=RuntimeError("Unexpected internal error")):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    "/api/t4/certificates/",
                    {
                        "event": self.event.pk,
                        "context_type": "participant",
                        "user": self.participant.pk,
                    },
                    format="json",
                )



class JudgeRecordAndVerificationAPITests(T4BaseTestCase):
    def test_valid_judge_record_generation_and_api(self):
        self.client.force_authenticate(user=self.organizer)
        resp = self.client.post(
            "/api/t4/judge-records/",
            {
                "event": self.event.pk,
                "judge": self.judge.pk,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["judge"], self.judge.username)
        self.assertEqual(resp.data["event"], self.event.pk)
        self.assertEqual(resp.data["algorithm"], "Ed25519")
        self.assertIn("payload", resp.data)
        self.assertIn("signature", resp.data)

        payload = resp.data["payload"]
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["record_type"], "judge_participation")
        self.assertEqual(payload["participation"]["assignment_count"], 1)
        self.assertEqual(payload["participation"]["scored_project_count"], 1)
        self.assertIn(self.project.pk, payload["participation"]["assigned_project_ids"])

        # No peer scores in payload
        self.assertNotIn("criteria_scores", json.dumps(payload))
        self.assertNotIn("comment", json.dumps(payload))

    def test_judge_with_no_participation_rejected(self):
        self.client.force_authenticate(user=self.organizer)
        resp = self.client.post(
            "/api/t4/judge-records/",
            {
                "event": self.event.pk,
                "judge": self.non_participating_judge.pk,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_judge_user_rejected(self):
        self.client.force_authenticate(user=self.organizer)
        resp = self.client.post(
            "/api/t4/judge-records/",
            {
                "event": self.event.pk,
                "judge": self.participant.pk,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_anonymous_post_judge_record_returns_401_or_403(self):
        # Must never return 500
        resp = self.client.post(
            "/api/t4/judge-records/",
            {
                "event": self.event.pk,
                "judge": self.judge.pk,
            },
            format="json",
        )
        self.assertIn(resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_public_verify_endpoint_valid_record(self):
        record = generate_judge_record(judge=self.judge, event=self.event, path=self.key_path)
        resp = self.client.get(f"/api/verify/{record.pk}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["record_id"], record.pk)
        self.assertTrue(resp.data["valid"])
        self.assertEqual(resp.data["algorithm"], "Ed25519")
        self.assertIn("public_key", resp.data)
        self.assertIn("signature", resp.data)

    def test_public_verify_endpoint_tampered_payload_returns_200_valid_false(self):
        record = generate_judge_record(judge=self.judge, event=self.event, path=self.key_path)
        # Mutate payload in DB
        record.payload["tampered"] = True
        record.save()

        resp = self.client.get(f"/api/verify/{record.pk}/")
        # NEVER return 4xx for invalid signature; must return 200 with valid=False
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data["valid"])

    def test_public_verify_endpoint_tampered_signature_returns_200_valid_false(self):
        record = generate_judge_record(judge=self.judge, event=self.event, path=self.key_path)
        # Mutate signature in DB
        sig = bytes(record.signature)
        record.signature = bytes([sig[0] ^ 0xFF]) + sig[1:]
        record.save()

        resp = self.client.get(f"/api/verify/{record.pk}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data["valid"])

    def test_verify_endpoint_malformed_id_returns_400(self):
        resp = self.client.get("/api/verify/not-an-id/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_verify_endpoint_unknown_numeric_id_returns_404(self):
        resp = self.client.get("/api/verify/999999/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_unexpected_exception_in_judge_record_post_propagates_not_400(self):
        self.client.force_authenticate(user=self.organizer)
        with patch("t4.views.generate_judge_record", side_effect=RuntimeError("Unexpected DB failure")):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    "/api/t4/judge-records/",
                    {
                        "event": self.event.pk,
                        "judge": self.judge.pk,
                    },
                    format="json",
                )
