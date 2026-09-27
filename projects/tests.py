from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from events.models import Event, Track
from teams.models import Team
from .models import Project


class ProjectsModelTest(TestCase):
    def setUp(self):
        self.event_a = Event.objects.create(
            name="Hackathon 2026 Alpha",
            submissions_close=timezone.now()
        )
        self.event_b = Event.objects.create(
            name="Hackathon 2026 Beta",
            submissions_close=timezone.now()
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
            status="draft"
        )
        self.assertEqual(project.title, "Dogfood Platform")
        self.assertEqual(project.status, "draft")
        self.assertEqual(project.team, self.team_a)
        self.assertEqual(project.track, self.track_a)
        self.assertEqual(str(project), "Dogfood Platform")

    def test_same_event_team_and_track_accepted(self):
        project = Project(
            team=self.team_a,
            track=self.track_a,
            title="Valid Same Event Project",
            summary="Summary of valid project",
            repo_url="https://example.com/repo",
            status="draft"
        )
        # Verify clean() passes without error
        project.clean()
        # Verify save() succeeds
        project.save()
        self.assertIsNotNone(project.pk)

    def test_cross_event_team_and_track_rejected_on_clean(self):
        project = Project(
            team=self.team_a,   # belongs to event_a
            track=self.track_b,  # belongs to event_b
            title="Invalid Cross Event Project",
            summary="Summary of invalid project",
            repo_url="https://example.com/repo",
            status="draft"
        )
        with self.assertRaises(ValidationError) as ctx:
            project.clean()
        self.assertIn("Project team and track must belong to the same event.", str(ctx.exception))

    def test_cross_event_team_and_track_rejected_on_save(self):
        project = Project(
            team=self.team_a,   # belongs to event_a
            track=self.track_b,  # belongs to event_b
            title="Invalid Cross Event Project",
            summary="Summary of invalid project",
            repo_url="https://example.com/repo",
            status="draft"
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
                status="draft"
            )
