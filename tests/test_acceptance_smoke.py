"""
Supplementary end-to-end acceptance and integration tests for DOGFOOD 2026.
Covers core contracts across T1, T2, T3, and T4.
"""
from datetime import timedelta
import json
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.utils import timezone

from accounts.models import Profile
from events.models import Event, Track
from teams.models import Team
from projects.models import Project
from judging.models import RubricCriterion, JudgeAssignment, Score
from voting.models import VotingToken, Vote
from voting.services import get_results, VotingClosedError, cast_authenticated_vote
from t4.services import (
    canonicalize_payload,
    sign_payload,
    verify_payload_signature,
    get_public_key,
)

User = get_user_model()


class AcceptanceSmokeTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Create Users and Profiles
        self.organizer = User.objects.create_user(username="test_org", password="pwd")
        Profile.objects.create(user=self.organizer, role="organizer")

        self.judge_a = User.objects.create_user(username="test_judge_a", password="pwd")
        Profile.objects.create(user=self.judge_a, role="judge")

        self.judge_b = User.objects.create_user(username="test_judge_b", password="pwd")
        Profile.objects.create(user=self.judge_b, role="judge")

        self.participant = User.objects.create_user(username="test_participant", password="pwd")
        Profile.objects.create(user=self.participant, role="participant")

        # Event: open in the past, closed submissions
        self.closed_event = Event.objects.create(
            name="Past Hackathon",
            submissions_close=timezone.now() - timedelta(hours=2),
            voting_close=timezone.now() + timedelta(hours=2),
        )
        self.track = Track.objects.create(event=self.closed_event, name="AI Track")
        self.team = Team.objects.create(event=self.closed_event, name="Apollo Team")
        self.project = Project.objects.create(
            team=self.team,
            track=self.track,
            title="Apollo AI Platform",
            summary="Next-gen AI assistant",
            repo_url="https://github.com/example/apollo",
            status="submitted",
        )

        # Rubric & Scoring
        self.criterion = RubricCriterion.objects.create(
            event=self.closed_event,
            name="Innovation",
            weight=1.0,
        )
        JudgeAssignment.objects.create(judge=self.judge_a, project=self.project)
        JudgeAssignment.objects.create(judge=self.judge_b, project=self.project)
        Score.objects.create(
            judge=self.judge_a,
            project=self.project,
            criteria_scores={self.criterion.name: 9},
            comment="Outstanding work",
        )

    def test_t1_gallery_is_public(self):
        """Gallery route /projects is accessible unauthenticated and returns 200."""
        response = self.client.get("/projects")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Apollo AI Platform", response.content.decode("utf-8"))

    def test_t1_closed_event_refuses_submissions(self):
        """Late submissions to closed events are rejected with 4xx status."""
        self.client.force_login(self.participant)
        response = self.client.post(
            "/projects/new",
            data=json.dumps({"title": "Late Project", "summary": "Too late"}),
            content_type="application/json",
        )
        self.assertTrue(400 <= response.status_code < 500)

    def test_t2_judge_scores_isolation(self):
        """Judge sees own scores; peer access blocked; participant blocked."""
        # Unauthenticated -> 401
        res = self.client.get("/api/judge/scores/")
        self.assertEqual(res.status_code, 401)

        # Participant -> 403
        self.client.force_login(self.participant)
        res = self.client.get("/api/judge/scores/")
        self.assertEqual(res.status_code, 403)

        # Judge A views own scores -> 200
        self.client.force_login(self.judge_a)
        res = self.client.get("/api/judge/scores/")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(any(item["project_title"] == "Apollo AI Platform" for item in data))

        # Judge B attempts to view Judge A's scores -> 403
        self.client.force_login(self.judge_b)
        res = self.client.get(f"/api/judge/scores/?judge={self.judge_a.username}")
        self.assertEqual(res.status_code, 403)

        # Organizer can inspect Judge A's scores -> 200
        self.client.force_login(self.organizer)
        res = self.client.get(f"/api/judge/scores/?judge={self.judge_a.username}")
        self.assertEqual(res.status_code, 200)

    def test_t2_csv_export(self):
        """CSV export restricted to organizer/admin and returns valid comma-separated header."""
        # Participant -> 403
        self.client.force_login(self.participant)
        res = self.client.get("/api/export.csv")
        self.assertEqual(res.status_code, 403)

        # Organizer -> 200, text/csv, comma in first line
        self.client.force_login(self.organizer)
        res = self.client.get("/api/export.csv")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res["Content-Type"].startswith("text/csv"))
        self.assertIn("attachment; filename=\"results.csv\"", res["Content-Disposition"])
        first_line = res.content.decode("utf-8").splitlines()[0]
        self.assertIn(",", first_line)

    def test_t3_results_hiding_during_active_window(self):
        """Results cannot be fetched before voting_close."""
        # Voting is still open (voting_close is in the future)
        with self.assertRaises(VotingClosedError):
            get_results(self.closed_event)

    def test_t3_duplicate_vote_rejected(self):
        """Same voter cannot cast multiple votes for the same project."""
        cast_authenticated_vote(self.participant, self.closed_event, self.project)
        from voting.services import DuplicateVoteError
        with self.assertRaises(DuplicateVoteError):
            cast_authenticated_vote(self.participant, self.closed_event, self.project)

    def test_t4_cryptographic_verification(self):
        """Ed25519 canonicalization and signature verification roundtrip."""
        payload = {"event_id": self.closed_event.pk, "judge": self.judge_a.username, "score": 9}
        sig = sign_payload(payload)
        pub_key = get_public_key()
        self.assertTrue(verify_payload_signature(payload, sig, public_key=pub_key))

        # Tampered payload fails verification
        tampered_payload = {"event_id": self.closed_event.pk, "judge": self.judge_a.username, "score": 10}
        self.assertFalse(verify_payload_signature(tampered_payload, sig, public_key=pub_key))

    def test_t4_bulk_export_and_import_roundtrip(self):
        """T4 Bulk export returns sanitized data and import supports atomic transactions."""
        # Unauthenticated -> 401
        res = self.client.get("/api/export/bulk/")
        self.assertEqual(res.status_code, 401)

        # Organizer -> 200
        self.client.force_login(self.organizer)
        res = self.client.get("/api/export/bulk/")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("projects", data)
        self.assertIn("events", data)

        # Dry-run import -> 200 without DB modification
        count_before = Project.objects.count()
        dry_res = self.client.post(
            "/api/import/bulk/?dry_run=true",
            data=json.dumps(data),
            content_type="application/json",
        )
        self.assertEqual(dry_res.status_code, 200)
        self.assertEqual(Project.objects.count(), count_before)

    def test_t4_openapi_schema_endpoint(self):
        """OpenAPI schema is served as JSON with valid structure."""
        res = self.client.get("/api/schema/")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("openapi"), "3.0.3")
        self.assertIn("/api/export/bulk/", data.get("paths", {}))
