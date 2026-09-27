from django.test import TestCase
from django.utils import timezone
from events.models import Event, Track
from teams.models import Team
from .models import Project


class ProjectsModelTest(TestCase):
    def test_project_creation(self):
        event = Event.objects.create(
            name="Hackathon 2026",
            submissions_close=timezone.now()
        )
        track = Track.objects.create(event=event, name="Web Track")
        team = Team.objects.create(event=event, name="DevSquad", invite_code="CODE456")
        project = Project.objects.create(
            team=team,
            track=track,
            title="Dogfood Platform",
            summary="Next-gen hackathon judging platform",
            repo_url="https://github.com/impetus-Dev/dogfood-2026",
            status="draft"
        )

        self.assertEqual(project.title, "Dogfood Platform")
        self.assertEqual(project.status, "draft")
        self.assertEqual(project.team, team)
        self.assertEqual(project.track, track)
        self.assertEqual(str(project), "Dogfood Platform")
