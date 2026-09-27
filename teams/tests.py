from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from events.models import Event
from .models import Team, TeamMembership


class TeamsModelTest(TestCase):
    def test_team_and_membership_creation(self):
        event = Event.objects.create(
            name="Hackathon 2026",
            submissions_close=timezone.now()
        )
        user = User.objects.create_user(username="teammember", password="password123")
        team = Team.objects.create(event=event, name="SuperTeam", invite_code="INVITE123")
        membership = TeamMembership.objects.create(team=team, user=user)

        self.assertEqual(team.name, "SuperTeam")
        self.assertEqual(membership.team, team)
        self.assertEqual(membership.user, user)
        self.assertEqual(str(team), "SuperTeam")
        self.assertIn("teammember", str(membership))
