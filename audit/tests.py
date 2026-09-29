"""
Tests for Phase 4: Audit trail and Comments.

Covers:
- AuditEvent model verification (5 fields, JSON metadata, no secrets)
- VOTE_CAST audit events (authenticated & link mode)
- VOTE_DUPLICATE_BLOCKED audit events (authenticated duplicate & link reuse)
- RESULTS_ACCESS_DENIED audit events (pre-close results access)
- Audit read path authorization (organizer only, participant/judge/anon denied)
- Project comments API (public read, authenticated/anonymous create, validation, draft protection)
- Full Phase 4 integration workflow
"""
import unittest.mock
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Profile
from audit.models import AuditEvent
from events.models import Event, Track
from projects.models import Project
from teams.models import Team
from voting.models import Comment, Vote, VotingToken


def _create_user_with_role(username, role="participant", **kw):
    user = User.objects.create_user(username=username, password="password123", **kw)
    Profile.objects.update_or_create(user=user, defaults={"role": role})
    return user


def _create_event(name="Phase 4 Event", voting_mode="authenticated", **kw):
    now = timezone.now()
    return Event.objects.create(
        name=name,
        submissions_close=kw.pop("submissions_close", now + timedelta(days=1)),
        voting_close=kw.pop("voting_close", now + timedelta(days=2)),
        voting_mode=voting_mode,
        **kw,
    )


def _create_project(event, title="Project 1", status="submitted"):
    track = Track.objects.create(event=event, name=f"Track for {title}")
    team = Team.objects.create(event=event, name=f"Team for {title}", invite_code=f"inv_{title}")
    return Project.objects.create(
        team=team,
        track=track,
        title=title,
        summary=f"Summary for {title}",
        repo_url="https://github.com/example/project",
        status=status,
    )



class AuditModelTests(TestCase):
    """Step 10: Audit model tests."""

    def test_audit_event_fields_and_creation(self):
        # 1. AuditEvent can be created.
        # 2. All five fields behave correctly.
        # 3. Metadata accepts JSON.
        meta = {"event_id": 1, "reason": "test_audit", "tags": ["voting", "security"]}
        event = AuditEvent.objects.create(
            actor="user:42",
            action="VOTE_CAST",
            target="vote:101",
            metadata=meta,
        )
        self.assertIsNotNone(event.pk)
        self.assertIsNotNone(event.timestamp)
        self.assertEqual(event.actor, "user:42")
        self.assertEqual(event.action, "VOTE_CAST")
        self.assertEqual(event.target, "vote:101")
        self.assertEqual(event.metadata, meta)
        self.assertEqual(event.metadata["tags"], ["voting", "security"])

    def test_raw_tokens_cannot_appear_in_generated_records(self):
        # 4. Raw tokens cannot appear in generated audit records.
        raw_token = "secret_raw_token_xyz_999"
        event = _create_event(voting_mode="link")
        project = _create_project(event)
        token_obj = VotingToken.objects.create(event=event, email="anon@example.com", token=raw_token)

        client = APIClient()
        resp = client.post(
            f"/api/vote/link/{raw_token}/",
            {"event": event.pk, "project": project.pk},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)

        # Inspect all audit events
        audit_events = AuditEvent.objects.filter(action="VOTE_CAST")
        self.assertTrue(audit_events.exists())
        for a in audit_events:
            self.assertNotIn(raw_token, str(a.actor))
            self.assertNotIn(raw_token, str(a.target))
            self.assertNotIn(raw_token, str(a.metadata))


class VoteAuditActionTests(TestCase):
    """Step 10: VOTE_CAST, VOTE_DUPLICATE_BLOCKED, and RESULTS_ACCESS_DENIED tests."""

    def setUp(self):
        self.now = timezone.now()
        self.auth_event = _create_event(
            name="Auth Event",
            voting_mode="authenticated",
            voting_close=self.now + timedelta(days=2),
        )
        self.auth_project = _create_project(self.auth_event, title="Auth Proj")
        self.user = _create_user_with_role("voter_alice", role="participant")

        self.link_event = _create_event(
            name="Link Event",
            voting_mode="link",
            voting_close=self.now + timedelta(days=2),
        )
        self.link_project = _create_project(self.link_event, title="Link Proj")
        self.raw_token = "valid_link_token_12345"
        self.token_obj = VotingToken.objects.create(
            event=self.link_event,
            email="link_voter@example.com",
            token=self.raw_token,
        )

    # 5, 7, 8: Authenticated successful vote creates VOTE_CAST with safe actor/target.
    def test_authenticated_successful_vote_creates_vote_cast(self):
        client = APIClient()
        client.force_login(self.user)
        resp = client.post(
            "/api/vote/",
            {"event": self.auth_event.pk, "project": self.auth_project.pk},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        vote_id = resp.json()["vote_id"]

        audit = AuditEvent.objects.filter(action="VOTE_CAST", target=f"vote:{vote_id}").first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.actor, f"user:{self.user.pk}")
        self.assertEqual(audit.target, f"vote:{vote_id}")
        self.assertEqual(audit.metadata["mode"], "authenticated")
        self.assertEqual(audit.metadata["event_id"], self.auth_event.pk)
        self.assertEqual(audit.metadata["project_id"], self.auth_project.pk)
        self.assertEqual(audit.metadata["vote_id"], vote_id)

    # 6, 7, 8, 9: Link successful vote creates VOTE_CAST with safe actor/target/metadata (no raw token).
    def test_link_successful_vote_creates_vote_cast(self):
        client = APIClient()
        resp = client.post(
            f"/api/vote/link/{self.raw_token}/",
            {"event": self.link_event.pk, "project": self.link_project.pk},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        vote_id = resp.json()["vote_id"]

        audit = AuditEvent.objects.filter(action="VOTE_CAST", target=f"vote:{vote_id}").first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.actor, "link")
        self.assertEqual(audit.target, f"vote:{vote_id}")
        self.assertEqual(audit.metadata["mode"], "link")
        self.assertEqual(audit.metadata["event_id"], self.link_event.pk)
        self.assertEqual(audit.metadata["project_id"], self.link_project.pk)
        self.assertNotIn(self.raw_token, str(audit.metadata))

    # 10, 12, 13: Authenticated duplicate vote creates VOTE_DUPLICATE_BLOCKED, returns 409, creates no extra Vote.
    def test_authenticated_duplicate_vote_creates_audit_event(self):
        client = APIClient()
        client.force_login(self.user)
        # First vote
        resp1 = client.post(
            "/api/vote/",
            {"event": self.auth_event.pk, "project": self.auth_project.pk},
            format="json",
        )
        self.assertEqual(resp1.status_code, 201)
        initial_vote_count = Vote.objects.count()

        # Duplicate vote attempt
        resp2 = client.post(
            "/api/vote/",
            {"event": self.auth_event.pk, "project": self.auth_project.pk},
            format="json",
        )
        self.assertEqual(resp2.status_code, 409)
        self.assertEqual(Vote.objects.count(), initial_vote_count)

        audit = AuditEvent.objects.filter(action="VOTE_DUPLICATE_BLOCKED").first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.actor, f"user:{self.user.pk}")
        self.assertEqual(audit.metadata["mode"], "authenticated")
        self.assertEqual(audit.metadata["event_id"], self.auth_event.pk)
        self.assertEqual(audit.metadata["project_id"], self.auth_project.pk)

    # 11, 12, 13: Link token reuse creates VOTE_DUPLICATE_BLOCKED, returns 409, no extra Vote.
    def test_link_token_reuse_creates_audit_event(self):
        client = APIClient()
        resp1 = client.post(
            f"/api/vote/link/{self.raw_token}/",
            {"event": self.link_event.pk, "project": self.link_project.pk},
            format="json",
        )
        self.assertEqual(resp1.status_code, 201)
        initial_vote_count = Vote.objects.count()

        # Reusing the token
        resp2 = client.post(
            f"/api/vote/link/{self.raw_token}/",
            {"event": self.link_event.pk, "project": self.link_project.pk},
            format="json",
        )
        self.assertEqual(resp2.status_code, 409)
        self.assertEqual(Vote.objects.count(), initial_vote_count)

        audit = AuditEvent.objects.filter(action="VOTE_DUPLICATE_BLOCKED").first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.actor, "link")
        self.assertEqual(audit.metadata["mode"], "link")
        self.assertEqual(audit.metadata["event_id"], self.link_event.pk)
        self.assertNotIn(self.raw_token, str(audit.metadata))

    # 14, 15, 16: Pre-close results request creates RESULTS_ACCESS_DENIED, returns exact 403, tally unexecuted.
    def test_results_before_close_creates_audit_event_and_tally_not_called(self):
        open_event = _create_event(name="Open Event", voting_close=self.now + timedelta(days=2))
        client = APIClient()

        with unittest.mock.patch("voting.services.tally_results") as mock_tally:
            resp = client.get(f"/api/results/{open_event.pk}/")

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json(), {"detail": "Results are hidden until voting closes."})
        mock_tally.assert_not_called()

        audit = AuditEvent.objects.filter(action="RESULTS_ACCESS_DENIED", target=f"event:{open_event.pk}").first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.actor, "anonymous")
        self.assertEqual(audit.metadata["event_id"], open_event.pk)
        self.assertEqual(audit.metadata["reason"], "voting_not_closed")


class AuditReadTests(TestCase):
    """Step 10: Audit read path authorization tests (GET /api/audit/)."""

    def setUp(self):
        self.organizer = _create_user_with_role("org_alice", role="organizer")
        self.admin_user = _create_user_with_role("admin_bob", role="admin")
        self.participant = _create_user_with_role("part_charlie", role="participant")
        self.judge = _create_user_with_role("judge_dan", role="judge")

        AuditEvent.objects.create(
            actor="user:1",
            action="VOTE_CAST",
            target="vote:10",
            metadata={"mode": "authenticated", "event_id": 1},
        )
        AuditEvent.objects.create(
            actor="anonymous",
            action="RESULTS_ACCESS_DENIED",
            target="event:1",
            metadata={"event_id": 1},
        )

    # 17: Organizer can read audit entries.
    def test_organizer_can_read_audit(self):
        client = APIClient()
        client.force_login(self.organizer)
        resp = client.get("/api/audit/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 2)
        # Check fields
        expected_keys = {"id", "timestamp", "actor", "action", "target", "metadata"}
        for item in data:
            self.assertEqual(set(item.keys()), expected_keys)

    def test_admin_can_read_audit(self):
        client = APIClient()
        client.force_login(self.admin_user)
        resp = client.get("/api/audit/")
        self.assertEqual(resp.status_code, 200)

    # 18: Participant cannot read audit entries (403).
    def test_participant_cannot_read_audit(self):
        client = APIClient()
        client.force_login(self.participant)
        resp = client.get("/api/audit/")
        self.assertEqual(resp.status_code, 403)

    # 19: Judge cannot read audit entries (403).
    def test_judge_cannot_read_audit(self):
        client = APIClient()
        client.force_login(self.judge)
        resp = client.get("/api/audit/")
        self.assertEqual(resp.status_code, 403)

    # 20: Anonymous cannot read audit entries (403).
    def test_anonymous_cannot_read_audit(self):
        client = APIClient()
        resp = client.get("/api/audit/")
        self.assertEqual(resp.status_code, 403)

    # 21: Raw tokens never appear in audit endpoint response.
    def test_raw_tokens_never_appear_in_audit_response(self):
        client = APIClient()
        client.force_login(self.organizer)
        resp = client.get("/api/audit/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode("utf-8")
        self.assertNotIn("secret_token", body)
        self.assertNotIn("password", body)
        self.assertNotIn("session", body)


class CommentsApiTests(TestCase):
    """Step 10: Comments API tests."""

    def setUp(self):
        self.event = _create_event(name="Comment Event")
        self.submitted_project = _create_project(self.event, title="Submitted P", status="submitted")
        self.draft_project = _create_project(self.event, title="Draft P", status="draft")
        self.user = _create_user_with_role("commenter_bob")

    # 22, 29, 30: GET comments works, returns comments in chronological order.
    def test_get_comments_submitted_project(self):
        c1 = Comment.objects.create(project=self.submitted_project, author_name="Alice", text="First comment")
        c2 = Comment.objects.create(project=self.submitted_project, author_name="Bob", text="Second comment")

        client = APIClient()
        resp = client.get(f"/api/projects/{self.submitted_project.pk}/comments/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["id"], c1.pk)
        self.assertEqual(data[0]["author_name"], "Alice")
        self.assertEqual(data[0]["text"], "First comment")
        self.assertEqual(data[1]["id"], c2.pk)
        self.assertEqual(data[1]["author_name"], "Bob")
        # Ensure chronological ordering
        self.assertLess(data[0]["id"], data[1]["id"])

    # 23, 31: POST valid comment works and returns no secret fields.
    def test_post_valid_comment(self):
        client = APIClient()
        payload = {"author_name": "Charlie", "text": "Great architecture!"}
        resp = client.post(
            f"/api/projects/{self.submitted_project.pk}/comments/",
            payload,
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["author_name"], "Charlie")
        self.assertEqual(data["text"], "Great architecture!")
        self.assertEqual(data["project"], self.submitted_project.pk)
        # Check fields: exactly safe fields
        expected_keys = {"id", "project", "author_name", "text", "created_at"}
        self.assertEqual(set(data.keys()), expected_keys)
        self.assertTrue(Comment.objects.filter(project=self.submitted_project, text="Great architecture!").exists())

    # 24: Blank author rejected (400).
    def test_blank_author_rejected(self):
        client = APIClient()
        resp = client.post(
            f"/api/projects/{self.submitted_project.pk}/comments/",
            {"author_name": "   ", "text": "Nice work!"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("author_name", resp.json())

    # 25: Blank text rejected (400).
    def test_blank_text_rejected(self):
        client = APIClient()
        resp = client.post(
            f"/api/projects/{self.submitted_project.pk}/comments/",
            {"author_name": "Dan", "text": "   "},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("text", resp.json())

    # 26: Oversized input rejected (400).
    def test_oversized_author_rejected(self):
        client = APIClient()
        resp = client.post(
            f"/api/projects/{self.submitted_project.pk}/comments/",
            {"author_name": "A" * 256, "text": "Valid text"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    # 27: Malformed payload returns clean 400.
    def test_malformed_payload_returns_400(self):
        client = APIClient()
        resp = client.post(
            f"/api/projects/{self.submitted_project.pk}/comments/",
            "not valid json string",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    # 28: Draft project comments rejected (400 on POST, 404 on GET).
    def test_draft_project_comments_rejected(self):
        client = APIClient()
        resp_post = client.post(
            f"/api/projects/{self.draft_project.pk}/comments/",
            {"author_name": "Eve", "text": "Draft comment"},
            format="json",
        )
        self.assertEqual(resp_post.status_code, 400)
        self.assertIn("detail", resp_post.json())

        resp_get = client.get(f"/api/projects/{self.draft_project.pk}/comments/")
        self.assertEqual(resp_get.status_code, 404)


class Phase4IntegrationTests(TestCase):
    """Step 11: End-to-end Phase 4 integration workflow."""

    def test_full_phase4_workflow(self):
        event = _create_event(
            name="Workflow Event",
            voting_mode="authenticated",
            voting_close=timezone.now() + timedelta(days=2),
        )
        project = _create_project(event, title="Integration Proj")
        voter = _create_user_with_role("voter_int", role="participant")
        organizer = _create_user_with_role("org_int", role="organizer")

        link_event = _create_event(
            name="Link Workflow Event",
            voting_mode="link",
            voting_close=timezone.now() + timedelta(days=2),
        )
        link_project = _create_project(link_event, title="Link Integration Proj")
        link_token = VotingToken.objects.create(
            event=link_event, email="link_int@example.com", token="tok_workflow_123"
        )

        client = APIClient()

        # 1. Authenticated vote -> VOTE_CAST
        client.force_login(voter)
        resp1 = client.post("/api/vote/", {"event": event.pk, "project": project.pk}, format="json")
        self.assertEqual(resp1.status_code, 201)
        vote_id = resp1.json()["vote_id"]
        self.assertTrue(AuditEvent.objects.filter(action="VOTE_CAST", target=f"vote:{vote_id}").exists())

        # 2. Same authenticated vote again -> 409 -> VOTE_DUPLICATE_BLOCKED
        resp2 = client.post("/api/vote/", {"event": event.pk, "project": project.pk}, format="json")
        self.assertEqual(resp2.status_code, 409)
        self.assertTrue(AuditEvent.objects.filter(action="VOTE_DUPLICATE_BLOCKED", target=f"project:{project.pk}").exists())

        # 3. Link vote -> VOTE_CAST
        link_client = APIClient()
        resp3 = link_client.post(
            f"/api/vote/link/{link_token.token}/",
            {"event": link_event.pk, "project": link_project.pk},
            format="json",
        )
        self.assertEqual(resp3.status_code, 201)
        link_vote_id = resp3.json()["vote_id"]
        self.assertTrue(AuditEvent.objects.filter(action="VOTE_CAST", target=f"vote:{link_vote_id}").exists())

        # 4. Reuse link token -> 409 -> VOTE_DUPLICATE_BLOCKED
        resp4 = link_client.post(
            f"/api/vote/link/{link_token.token}/",
            {"event": link_event.pk, "project": link_project.pk},
            format="json",
        )
        self.assertEqual(resp4.status_code, 409)
        self.assertTrue(AuditEvent.objects.filter(action="VOTE_DUPLICATE_BLOCKED", actor="link").exists())

        # 5. Results before close -> 403 -> RESULTS_ACCESS_DENIED
        resp5 = client.get(f"/api/results/{event.pk}/")
        self.assertEqual(resp5.status_code, 403)
        self.assertTrue(AuditEvent.objects.filter(action="RESULTS_ACCESS_DENIED", target=f"event:{event.pk}").exists())

        # 6. Results after close -> 200 -> no new RESULTS_ACCESS_DENIED
        denied_count_before = AuditEvent.objects.filter(action="RESULTS_ACCESS_DENIED").count()
        event.voting_close = timezone.now() - timedelta(hours=1)
        event.save(update_fields=["voting_close"])
        resp6 = client.get(f"/api/results/{event.pk}/")
        self.assertEqual(resp6.status_code, 200)
        self.assertEqual(AuditEvent.objects.filter(action="RESULTS_ACCESS_DENIED").count(), denied_count_before)

        # 7. Comments POST -> stored Comment
        resp7 = client.post(
            f"/api/projects/{project.pk}/comments/",
            {"author_name": "Integration Tester", "text": "End-to-end verified"},
            format="json",
        )
        self.assertEqual(resp7.status_code, 201)
        comment_id = resp7.json()["id"]

        # 8. Comments GET -> public comments
        resp8 = client.get(f"/api/projects/{project.pk}/comments/")
        self.assertEqual(resp8.status_code, 200)
        comment_ids = [c["id"] for c in resp8.json()]
        self.assertIn(comment_id, comment_ids)

        # 9. Audit read -> organizer sees real events
        org_client = APIClient()
        org_client.force_login(organizer)
        resp9 = org_client.get("/api/audit/")
        self.assertEqual(resp9.status_code, 200)
        actions = [a["action"] for a in resp9.json()]
        self.assertIn("VOTE_CAST", actions)
        self.assertIn("VOTE_DUPLICATE_BLOCKED", actions)
        self.assertIn("RESULTS_ACCESS_DENIED", actions)
