from datetime import timedelta
import json

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event, Track
from teams.models import Team, TeamMembership
from .models import Project


class ProjectsModelTest(TestCase):
    def setUp(self):
        self.event_a = Event.objects.create(
            name="Hackathon 2026 Alpha",
            submissions_close=timezone.now(),
        )
        self.event_b = Event.objects.create(
            name="Hackathon 2026 Beta",
            submissions_close=timezone.now(),
        )
        self.track_a = Track.objects.create(event=self.event_a, name="AI / ML")
        self.track_b = Track.objects.create(event=self.event_b, name="Web3")
        self.team_a = Team.objects.create(event=self.event_a, name="Alpha Team", invite_code="ALPHA1")
        self.team_b = Team.objects.create(event=self.event_b, name="Beta Team", invite_code="BETA1")

    def test_project_creation(self):
        project = Project.objects.create(
            team=self.team_a,
            track=self.track_a,
            title="Dogfood Platform",
            summary="Next-gen hackathon judging platform",
            repo_url="https://github.com/impetus-Dev/dogfood-2026",
            status="draft",
        )
        self.assertEqual(project.title, "Dogfood Platform")
        self.assertEqual(project.status, "draft")
        self.assertIsNone(project.submitted_at)
        self.assertEqual(project.team, self.team_a)
        self.assertEqual(project.track, self.track_a)
        self.assertEqual(str(project), "Dogfood Platform")

    def test_submitted_status_supported(self):
        project = Project.objects.create(
            team=self.team_a,
            track=self.track_a,
            title="Submitted Project",
            summary="Already submitted",
            repo_url="https://github.com/impetus-Dev/dogfood-2026",
            status="submitted",
            submitted_at=timezone.now(),
        )
        self.assertEqual(project.status, "submitted")
        self.assertIsNotNone(project.submitted_at)

    def test_same_event_team_and_track_accepted(self):
        project = Project(
            team=self.team_a,
            track=self.track_a,
            title="Valid Same Event Project",
            summary="Summary of valid project",
            repo_url="https://example.com/repo",
            status="draft",
        )
        project.clean()
        project.save()
        self.assertIsNotNone(project.pk)

    def test_cross_event_team_and_track_rejected_on_clean(self):
        project = Project(
            team=self.team_a,
            track=self.track_b,
            title="Invalid Cross Event Project",
            summary="Summary of invalid project",
            repo_url="https://example.com/repo",
            status="draft",
        )
        with self.assertRaises(ValidationError) as ctx:
            project.clean()
        self.assertIn("Project team and track must belong to the same event.", str(ctx.exception))

    def test_cross_event_team_and_track_rejected_on_save(self):
        project = Project(
            team=self.team_a,
            track=self.track_b,
            title="Invalid Cross Event Project",
            summary="Summary of invalid project",
            repo_url="https://example.com/repo",
            status="draft",
        )
        with self.assertRaises(ValidationError):
            project.save()

    def test_cross_event_team_and_track_rejected_on_create(self):
        with self.assertRaises(ValidationError):
            Project.objects.create(
                team=self.team_a,
                track=self.track_b,
                title="Invalid Cross Event Create",
                summary="Summary of invalid create",
                repo_url="https://example.com/repo",
                status="draft",
            )


class ProjectAuthAndCreationTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.event_open = Event.objects.create(
            name="Open Event",
            submissions_close=timezone.now() + timedelta(days=7),
        )
        self.event_closed = Event.objects.create(
            name="Closed Event",
            submissions_close=timezone.now() - timedelta(days=1),
        )
        self.track_open = Track.objects.create(event=self.event_open, name="AI")
        self.track_closed = Track.objects.create(event=self.event_closed, name="Web")

        self.user_member = User.objects.create_user(username="member", password="password123")
        self.user_non_member = User.objects.create_user(username="stranger", password="password123")

        self.team_open = Team.objects.create(event=self.event_open, name="Open Team", invite_code="OPEN1")
        TeamMembership.objects.create(team=self.team_open, user=self.user_member)

    def test_anonymous_create_blocked(self):
        url = reverse("projects:create")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

        response_post = self.client.post(url, {
            "title": "Anon Project",
            "summary": "Anon Summary",
            "repo_url": "https://github.com/anon/repo",
            "team": self.team_open.id,
            "track": self.track_open.id,
        })
        self.assertEqual(response_post.status_code, 302)
        self.assertIn(reverse("login"), response_post.url)
        self.assertEqual(Project.objects.count(), 0)

    def test_anonymous_json_create_returns_401(self):
        url = reverse("projects:create")
        response = self.client.post(
            url,
            json.dumps({"title": "Anon JSON"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_team_member_can_create_draft_project(self):
        self.client.force_login(self.user_member)
        url = reverse("projects:create")
        response = self.client.post(url, {
            "title": "My Awesome Project",
            "summary": "An awesome hackathon project",
            "repo_url": "https://github.com/member/repo",
            "team": self.team_open.id,
            "track": self.track_open.id,
        })
        self.assertEqual(response.status_code, 302)
        project = Project.objects.get(title="My Awesome Project")
        self.assertEqual(project.status, "draft")
        self.assertIsNone(project.submitted_at)
        self.assertEqual(project.team, self.team_open)
        self.assertEqual(project.track, self.track_open)
        self.assertRedirects(response, reverse("projects:detail", args=[project.id]))

    def test_non_member_cannot_create_for_another_team(self):
        self.client.force_login(self.user_non_member)
        url = reverse("projects:create")
        response = self.client.post(url, {
            "title": "Unauthorized Project",
            "summary": "Trying to create for a team I do not belong to",
            "repo_url": "https://github.com/stranger/repo",
            "team": self.team_open.id,
            "track": self.track_open.id,
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Project.objects.count(), 0)

    def test_cross_event_creation_rejected_with_400(self):
        self.client.force_login(self.user_member)
        url = reverse("projects:create")
        response = self.client.post(url, {
            "title": "Mismatched Project",
            "summary": "Cross-event team and track",
            "repo_url": "https://github.com/member/repo",
            "team": self.team_open.id,
            "track": self.track_closed.id,
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Project.objects.count(), 0)


class ProjectCrashSafetyAndAcceptanceProbeTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.event_open = Event.objects.create(
            name="Open Event",
            submissions_close=timezone.now() + timedelta(days=7),
        )
        self.event_closed = Event.objects.create(
            name="Closed Event",
            submissions_close=timezone.now() - timedelta(days=1),
        )
        self.participant = User.objects.create_user(username="participant_tester", password="password123")

    def test_minimal_probe_returns_400_on_open_event(self):
        """Checker probe payload with only title and summary returns 400, NOT 500."""
        self.client.force_login(self.participant)
        response = self.client.post(
            "/projects/new",
            json.dumps({"title": "dogfood-late-submission-probe", "summary": "probe"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("errors", data)
        self.assertIn("team", data["errors"])
        self.assertIn("track", data["errors"])
        self.assertIn("repo_url", data["errors"])

    def test_minimal_probe_returns_400_on_closed_event(self):
        """Checker probe payload on closed event also returns 400, NOT 500."""
        self.client.force_login(self.participant)
        response = self.client.post(
            "/projects/new/",
            json.dumps({"title": "dogfood-late-submission-probe", "summary": "probe"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_empty_json_body_returns_400(self):
        self.client.force_login(self.participant)
        response = self.client.post(
            "/projects/new/",
            json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_invalid_json_body_returns_400(self):
        self.client.force_login(self.participant)
        response = self.client.post(
            "/projects/new/",
            "not valid json string",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


class ProjectEditAndSubmitTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.event_open = Event.objects.create(
            name="Active Hackathon",
            submissions_close=timezone.now() + timedelta(days=5),
        )
        self.event_closed = Event.objects.create(
            name="Past Hackathon",
            submissions_close=timezone.now() - timedelta(days=2),
        )

        self.track_open1 = Track.objects.create(event=self.event_open, name="AI / ML")
        self.track_open2 = Track.objects.create(event=self.event_open, name="Productivity")
        self.track_closed = Track.objects.create(event=self.event_closed, name="Legacy")

        self.member = User.objects.create_user(username="lead_dev", password="password123")
        self.outsider = User.objects.create_user(username="outsider", password="password123")

        self.team_open = Team.objects.create(event=self.event_open, name="Dev Team", invite_code="DEV1")
        TeamMembership.objects.create(team=self.team_open, user=self.member)

        self.team_closed = Team.objects.create(event=self.event_closed, name="Old Team", invite_code="OLD1")
        TeamMembership.objects.create(team=self.team_closed, user=self.member)

        self.project_open = Project.objects.create(
            team=self.team_open,
            track=self.track_open1,
            title="Active Draft",
            summary="Still working on it",
            repo_url="https://github.com/team/active",
            status="draft",
        )

        self.project_closed = Project.objects.create(
            team=self.team_closed,
            track=self.track_closed,
            title="Late Project",
            summary="Finished too late",
            repo_url="https://github.com/team/late",
            status="draft",
        )

    def test_anonymous_edit_blocked(self):
        response = self.client.get(reverse("projects:edit", args=[self.project_open.id]))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_anonymous_submit_blocked(self):
        response = self.client.post(reverse("projects:submit", args=[self.project_open.id]))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
        self.project_open.refresh_from_db()
        self.assertEqual(self.project_open.status, "draft")

    def test_outsider_cannot_edit(self):
        self.client.force_login(self.outsider)
        response = self.client.get(reverse("projects:edit", args=[self.project_open.id]))
        self.assertEqual(response.status_code, 403)

        response_post = self.client.post(reverse("projects:edit", args=[self.project_open.id]), {
            "title": "Hacked Title",
            "summary": "Hacked",
            "repo_url": "https://hacked.com",
            "track": self.track_open1.id,
        })
        self.assertEqual(response_post.status_code, 403)
        self.project_open.refresh_from_db()
        self.assertEqual(self.project_open.title, "Active Draft")

    def test_outsider_cannot_submit(self):
        self.client.force_login(self.outsider)
        response = self.client.post(reverse("projects:submit", args=[self.project_open.id]))
        self.assertEqual(response.status_code, 403)
        self.project_open.refresh_from_db()
        self.assertEqual(self.project_open.status, "draft")

    def test_team_member_can_edit_draft_fields(self):
        self.client.force_login(self.member)
        response = self.client.post(reverse("projects:edit", args=[self.project_open.id]), {
            "title": "Refined Active Project",
            "summary": "Much better summary",
            "repo_url": "https://github.com/team/refined",
            "track": self.track_open2.id,
        })
        self.assertEqual(response.status_code, 302)
        self.project_open.refresh_from_db()
        self.assertEqual(self.project_open.title, "Refined Active Project")
        self.assertEqual(self.project_open.summary, "Much better summary")
        self.assertEqual(self.project_open.repo_url, "https://github.com/team/refined")
        self.assertEqual(self.project_open.track, self.track_open2)

    def test_edit_rejects_cross_event_track(self):
        self.client.force_login(self.member)
        response = self.client.post(reverse("projects:edit", args=[self.project_open.id]), {
            "title": "Cross Event Edit",
            "summary": "Cross Event Summary",
            "repo_url": "https://github.com/team/refined",
            "track": self.track_closed.id,
        })
        self.assertEqual(response.status_code, 400)
        self.project_open.refresh_from_db()
        self.assertEqual(self.project_open.title, "Active Draft")

    def test_valid_open_event_submission_succeeds(self):
        self.client.force_login(self.member)
        response = self.client.post(reverse("projects:submit", args=[self.project_open.id]))
        self.assertEqual(response.status_code, 302)
        self.project_open.refresh_from_db()
        self.assertEqual(self.project_open.status, "submitted")
        self.assertIsNotNone(self.project_open.submitted_at)

    def test_already_submitted_project_cannot_be_submitted_again(self):
        self.client.force_login(self.member)
        # First submission
        self.client.post(reverse("projects:submit", args=[self.project_open.id]))
        self.project_open.refresh_from_db()
        initial_submitted_at = self.project_open.submitted_at

        # Second submission attempt
        response = self.client.post(reverse("projects:submit", args=[self.project_open.id]))
        self.assertEqual(response.status_code, 400)
        self.project_open.refresh_from_db()
        self.assertEqual(self.project_open.status, "submitted")
        self.assertEqual(self.project_open.submitted_at, initial_submitted_at)

    def test_submitted_project_cannot_be_edited(self):
        self.client.force_login(self.member)
        # Submit first
        self.client.post(reverse("projects:submit", args=[self.project_open.id]))
        self.project_open.refresh_from_db()

        # Attempt edit
        response = self.client.get(reverse("projects:edit", args=[self.project_open.id]))
        self.assertEqual(response.status_code, 400)

        response_post = self.client.post(reverse("projects:edit", args=[self.project_open.id]), {
            "title": "Post-Submission Edit",
            "summary": "Should be blocked",
            "repo_url": "https://github.com/team/blocked",
            "track": self.track_open1.id,
        })
        self.assertEqual(response_post.status_code, 400)
        self.project_open.refresh_from_db()
        self.assertEqual(self.project_open.title, "Active Draft")

    def test_late_submission_on_closed_event_fails_with_400(self):
        self.client.force_login(self.member)
        response = self.client.post(reverse("projects:submit", args=[self.project_closed.id]))
        self.assertEqual(response.status_code, 400)
        self.project_closed.refresh_from_db()
        self.assertEqual(self.project_closed.status, "draft")
        self.assertIsNone(self.project_closed.submitted_at)
