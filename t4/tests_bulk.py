"""
Security & Adversarial test suite for T4-A Bulk Export & Import Engine and OpenAPI Schema.
Covers:
- Valid export and import roundtrip
- Secret sanitization and leak prevention
- Adversarial payloads (injected secrets, duplicate external_ids, broken FKs, cross-event violations)
- Role-based authorization isolation (anonymous 401, participant/judge 403, organizer/admin 200)
- Dry-run verification (strictly zero DB writes)
- Atomic all-or-nothing rollback on partial failure
- OpenAPI schema endpoint verification
"""
from datetime import datetime, timezone, timedelta
import json
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from rest_framework import status

from accounts.models import Profile
from events.models import Event, Track
from teams.models import Team, TeamMembership
from projects.models import Project
from t4.bulk_services import FORBIDDEN_SECRET_KEYS, scrub_and_verify_secrets

User = get_user_model()


class BulkExportImportSecurityTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Users with various roles
        self.organizer = User.objects.create_user(username="org_user", password="secret_password_1")
        Profile.objects.create(user=self.organizer, role="organizer")

        self.admin_user = User.objects.create_user(username="admin_user", password="secret_password_2")
        Profile.objects.create(user=self.admin_user, role="admin")

        self.judge = User.objects.create_user(username="judge_user", password="secret_password_3")
        Profile.objects.create(user=self.judge, role="judge")

        self.participant = User.objects.create_user(username="part_user", password="secret_password_4")
        Profile.objects.create(user=self.participant, role="participant")

        # Initial seed data
        now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        self.event1 = Event.objects.create(
            name="Alpha Hackathon",
            external_id="evt_alpha",
            submissions_close=now + timedelta(days=2),
            voting_close=now + timedelta(days=4),
            voting_mode="authenticated",
        )
        self.track1 = Track.objects.create(
            event=self.event1,
            name="Developer Tools",
            external_id="trk_dev",
        )
        self.team1 = Team.objects.create(
            event=self.event1,
            name="Team Falcon",
            external_id="tm_falcon",
            invite_code="inv_falcon_123",
        )
        TeamMembership.objects.create(team=self.team1, user=self.participant)

        self.project1 = Project.objects.create(
            team=self.team1,
            track=self.track1,
            title="Falcon IDE",
            summary="Next-generation cloud editor",
            repo_url="https://github.com/falcon/ide",
            external_id="prj_falcon",
            status="submitted",
            submitted_at=now,
        )

    # --- Authorization & Role Isolation Tests ---

    def test_export_unauthenticated_returns_401(self):
        """Anonymous callers are rejected with 401 Unauthorized."""
        res = self.client.get("/api/export/bulk/")
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        res_t4 = self.client.get("/api/t4/export/")
        self.assertEqual(res_t4.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_export_participant_and_judge_blocked_403(self):
        """Participants and Judges cannot access bulk export."""
        self.client.force_login(self.participant)
        res = self.client.get("/api/export/bulk/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_login(self.judge)
        res = self.client.get("/api/export/bulk/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_export_organizer_and_admin_allowed_200(self):
        """Organizers and Admins can export bulk data."""
        self.client.force_login(self.organizer)
        res = self.client.get("/api/export/bulk/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.client.force_login(self.admin_user)
        res = self.client.get("/api/t4/export/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_import_unauthenticated_returns_401(self):
        """Anonymous callers cannot import data."""
        res = self.client.post("/api/import/bulk/", data={"events": []}, content_type="application/json")
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_import_participant_and_judge_blocked_403(self):
        """Participants and judges cannot invoke bulk import."""
        self.client.force_login(self.participant)
        res = self.client.post("/api/import/bulk/", data={"events": []}, content_type="application/json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_login(self.judge)
        res = self.client.post("/api/import/bulk/", data={"events": []}, content_type="application/json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    # --- Secret Sanitization & Exclusion Tests ---

    def test_export_absolute_secret_exclusion(self):
        """Verify that zero passwords, hashes, tokens, or private keys leak into the export payload."""
        self.client.force_login(self.organizer)
        res = self.client.get("/api/export/bulk/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        payload = res.json()

        # Automated check across entire JSON document
        raw_text = json.dumps(payload).lower()
        for forbidden in FORBIDDEN_SECRET_KEYS:
            if forbidden == "token":
                # Ensure no voting token or auth token exists
                self.assertNotIn("voting_token", raw_text)
                self.assertNotIn("session_token", raw_text)
                self.assertNotIn("csrf_token", raw_text)
            else:
                self.assertNotIn(forbidden, raw_text)

        # Confirm users' passwords do not appear in string
        self.assertNotIn("secret_password_1", raw_text)
        self.assertNotIn("pbkdf2", raw_text)
        self.assertNotIn("argon2", raw_text)

        # Direct verification via recursive scrubber
        scrub_and_verify_secrets(payload)

    # --- Dry-Run Simulation Tests ---

    def test_import_dry_run_makes_zero_database_writes(self):
        """Ensure dry_run=true calculates prospective creations/updates without modifying DB."""
        self.client.force_login(self.organizer)

        counts_before = {
            "events": Event.objects.count(),
            "tracks": Track.objects.count(),
            "teams": Team.objects.count(),
            "projects": Project.objects.count(),
        }

        now = datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc).isoformat()
        import_payload = {
            "events": [
                {
                    "name": "Beta Hackathon",
                    "external_id": "evt_beta",
                    "submissions_close": now,
                }
            ],
            "tracks": [
                {
                    "name": "AI & ML",
                    "external_id": "trk_ai",
                    "event_external_id": "evt_beta",
                }
            ],
            "teams": [
                {
                    "name": "Quantum Team",
                    "external_id": "tm_quantum",
                    "event_external_id": "evt_beta",
                    "members": ["quantum_coder"],
                }
            ],
            "projects": [
                {
                    "title": "Quantum Assistant",
                    "summary": "AI tool for quantum circuits",
                    "repo_url": "https://github.com/quantum/assistant",
                    "external_id": "prj_quantum",
                    "team_external_id": "tm_quantum",
                    "track_external_id": "trk_ai",
                }
            ],
        }

        # Dry run via query param
        res = self.client.post(
            "/api/import/bulk/?dry_run=true",
            data=json.dumps(import_payload),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertEqual(data["created"], 4)  # 1 event + 1 track + 1 team + 1 project
        self.assertEqual(data["updated"], 0)
        self.assertEqual(data["errors"], [])

        # STRICT DB ASSERTION: zero records were written!
        counts_after = {
            "events": Event.objects.count(),
            "tracks": Track.objects.count(),
            "teams": Team.objects.count(),
            "projects": Project.objects.count(),
        }
        self.assertEqual(counts_before, counts_after)

    # --- Valid Roundtrip & External ID Reconciliation ---

    def test_export_import_roundtrip_and_updates(self):
        """Export current database, update a title, import back, verify update occurred cleanly."""
        self.client.force_login(self.organizer)

        # 1. Export
        export_res = self.client.get("/api/export/bulk/")
        self.assertEqual(export_res.status_code, status.HTTP_200_OK)
        export_data = export_res.json()

        # 2. Modify title and add new track
        export_data["projects"][0]["title"] = "Falcon IDE Enterprise Edition"
        export_data["tracks"].append({
            "name": "Robotics Track",
            "external_id": "trk_robotics",
            "event_external_id": "evt_alpha",
        })

        # 3. Import
        import_res = self.client.post(
            "/api/import/bulk/",
            data=json.dumps(export_data),
            content_type="application/json",
        )
        self.assertEqual(import_res.status_code, status.HTTP_200_OK)
        import_summary = import_res.json()
        self.assertGreaterEqual(import_summary["updated"], 1)
        self.assertGreaterEqual(import_summary["created"], 1)
        self.assertEqual(import_summary["errors"], [])

        # 4. Verify update in DB
        self.project1.refresh_from_db()
        self.assertEqual(self.project1.title, "Falcon IDE Enterprise Edition")
        self.assertTrue(Track.objects.filter(external_id="trk_robotics").exists())

    # --- Adversarial & Failure Rollback Tests ---

    def test_adversarial_injected_password_rejected_or_ignored(self):
        """Import payload attempting to inject password or override credentials fails safely."""
        self.client.force_login(self.organizer)

        malicious_payload = {
            "teams": [
                {
                    "name": "Hacker Team",
                    "external_id": "tm_hack",
                    "event_external_id": "evt_alpha",
                    "members": [
                        {
                            "username": "victim_user",
                            "password": "injected_evil_password",
                        }
                    ],
                }
            ]
        }

        res = self.client.post(
            "/api/import/bulk/",
            data=json.dumps(malicious_payload),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Verify that created user does not have the injected password
        victim = User.objects.get(username="victim_user")
        self.assertFalse(victim.check_password("injected_evil_password"))
        self.assertFalse(victim.has_usable_password())

    def test_duplicate_external_id_in_payload_rejected(self):
        """Duplicate external_id within payload is caught during pre-validation."""
        self.client.force_login(self.organizer)

        bad_payload = {
            "tracks": [
                {"name": "Track A", "external_id": "trk_dup", "event_external_id": "evt_alpha"},
                {"name": "Track B", "external_id": "trk_dup", "event_external_id": "evt_alpha"},
            ]
        }

        res = self.client.post(
            "/api/import/bulk/",
            data=json.dumps(bad_payload),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        data = res.json()
        self.assertTrue(any("Duplicate track external_id: 'trk_dup'" in err for err in data["errors"]))

    def test_broken_foreign_key_rejected_in_prevalidation(self):
        """Project referencing non-existent track or team fails pre-validation with zero DB writes."""
        self.client.force_login(self.organizer)

        counts_before = Project.objects.count()

        bad_payload = {
            "projects": [
                {
                    "title": "Broken Project",
                    "summary": "Has no real track",
                    "repo_url": "https://example.org/broken",
                    "external_id": "prj_broken",
                    "team_external_id": "tm_falcon",
                    "track_external_id": "trk_nonexistent_999",
                }
            ]
        }

        res = self.client.post(
            "/api/import/bulk/",
            data=json.dumps(bad_payload),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        data = res.json()
        self.assertTrue(any("non-existent track 'trk_nonexistent_999'" in err for err in data["errors"]))

        # Database remained completely untouched
        self.assertEqual(Project.objects.count(), counts_before)

    def test_atomic_rollback_on_partial_failure(self):
        """If entry 3 in a batch fails validation or integrity, records 1 and 2 are rolled back."""
        self.client.force_login(self.organizer)

        counts_before = Track.objects.count()

        # Event Gamma with 2 valid tracks and 1 track with invalid name/type
        now = datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc).isoformat()
        payload = {
            "events": [{"name": "Gamma Event", "external_id": "evt_gamma", "submissions_close": now}],
            "tracks": [
                {"name": "Valid Track 1", "external_id": "trk_g1", "event_external_id": "evt_gamma"},
                {"name": "Valid Track 2", "external_id": "trk_g2", "event_external_id": "evt_gamma"},
                {"name": "", "external_id": "trk_g3", "event_external_id": "evt_gamma"},  # Missing name!
            ],
        }

        res = self.client.post(
            "/api/import/bulk/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # Neither Gamma Event nor Track 1 nor Track 2 were created!
        self.assertEqual(Track.objects.count(), counts_before)
        self.assertFalse(Event.objects.filter(external_id="evt_gamma").exists())
        self.assertFalse(Track.objects.filter(external_id="trk_g1").exists())

    # --- OpenAPI 3.x Specification Tests ---

    def test_openapi_schema_endpoints(self):
        """OpenAPI schema is publicly reachable and returns valid 3.0.3 specification."""
        for endpoint in ["/api/schema/", "/api/openapi.json"]:
            res = self.client.get(endpoint)
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            schema = res.json()
            self.assertEqual(schema.get("openapi"), "3.0.3")
            self.assertIn("paths", schema)
            # Verify core endpoints are documented
            self.assertIn("/api/export/bulk/", schema["paths"])
            self.assertIn("/api/import/bulk/", schema["paths"])
            self.assertIn("/api/judge/scores/", schema["paths"])
            self.assertIn("/api/export.csv", schema["paths"])
            self.assertIn("/projects", schema["paths"])
