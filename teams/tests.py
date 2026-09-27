from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from .models import Team, TeamMembership
from .views import generate_invite_code


class TeamsModelTest(TestCase):
    """Model-level tests for Team and TeamMembership."""

    def setUp(self):
        self.event = Event.objects.create(
            name="Hackathon 2026",
            submissions_close=timezone.now(),
        )
        self.user = User.objects.create_user(username="teammember", password="password123")

    def test_team_and_membership_creation(self):
        """Team can be created with valid Event, invite_code is stored."""
        team = Team.objects.create(event=self.event, name="SuperTeam", invite_code="INVITE123")
        membership = TeamMembership.objects.create(team=team, user=self.user)

        self.assertEqual(team.name, "SuperTeam")
        self.assertEqual(team.event, self.event)
        self.assertEqual(team.invite_code, "INVITE123")
        self.assertEqual(membership.team, team)
        self.assertEqual(membership.user, self.user)
        self.assertEqual(str(team), "SuperTeam")
        self.assertIn("teammember", str(membership))

    def test_invite_code_uniqueness(self):
        """invite_code must be unique across teams."""
        Team.objects.create(event=self.event, name="Team 1", invite_code="DUPLICATE_CODE")
        with self.assertRaises(IntegrityError):
            Team.objects.create(event=self.event, name="Team 2", invite_code="DUPLICATE_CODE")

    def test_membership_uniqueness_for_same_user_and_team(self):
        """TeamMembership unique_together prevents same user in same team twice."""
        team = Team.objects.create(event=self.event, name="UniqueTeam", invite_code="CODE_UNIQ")
        TeamMembership.objects.create(team=team, user=self.user)
        with self.assertRaises(IntegrityError):
            TeamMembership.objects.create(team=team, user=self.user)

    def test_generate_invite_code_format(self):
        """generate_invite_code returns a non-empty string under 64 characters."""
        code = generate_invite_code()
        self.assertTrue(isinstance(code, str))
        self.assertGreater(len(code), 10)
        self.assertLessEqual(len(code), 64)


class TeamAuthAndCreationTest(TestCase):
    """Tests for authentication and team creation flows."""

    def setUp(self):
        self.client = Client()
        self.event = Event.objects.create(
            name="Demo Hackathon",
            submissions_close=timezone.now(),
        )
        self.user = User.objects.create_user(username="creator", password="password123")

    def test_unauthenticated_user_cannot_create_team_get(self):
        """GET /teams/create/ redirects unauthenticated user to login."""
        response = self.client.get(reverse("teams:create"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_unauthenticated_user_cannot_create_team_post(self):
        """POST /teams/create/ redirects unauthenticated user to login without creating team."""
        initial_count = Team.objects.count()
        response = self.client.post(
            reverse("teams:create"),
            {"name": "SecretTeam", "event_id": self.event.id},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
        self.assertEqual(Team.objects.count(), initial_count)

    def test_authenticated_user_can_create_team(self):
        """Authenticated user can create a team and becomes creator member."""
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("teams:create"),
            {"name": "RocketTeam", "event_id": self.event.id},
        )
        self.assertEqual(response.status_code, 302)

        team = Team.objects.get(name="RocketTeam")
        self.assertEqual(team.event, self.event)
        self.assertTrue(team.invite_code)
        self.assertLessEqual(len(team.invite_code), 64)

        # Creator automatically becomes a member
        self.assertTrue(
            TeamMembership.objects.filter(team=team, user=self.user).exists(),
            "Creator was not added to TeamMembership.",
        )
        self.assertEqual(team.memberships.count(), 1)
        self.assertRedirects(response, reverse("teams:detail", args=[team.id]))

    def test_create_team_validation_missing_name(self):
        """Submitting empty team name returns 400 with error."""
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("teams:create"),
            {"name": "   ", "event_id": self.event.id},
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Team name is required", status_code=400)
        self.assertEqual(Team.objects.filter(event=self.event).count(), 0)

    def test_create_team_validation_missing_event(self):
        """Submitting missing event_id returns 400 with error."""
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("teams:create"),
            {"name": "NoEventTeam", "event_id": ""},
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Event selection is required", status_code=400)

    def test_create_team_validation_invalid_event(self):
        """Submitting non-existent event_id returns 400 with error."""
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("teams:create"),
            {"name": "BadEventTeam", "event_id": 999999},
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Selected event does not exist", status_code=400)


class TeamInviteGetReadOnlyTest(TestCase):
    """Tests ensuring GET /teams/join/<invite_code>/ is strictly read-only and idempotent."""

    def setUp(self):
        self.client = Client()
        self.event = Event.objects.create(
            name="GetCheck Event",
            submissions_close=timezone.now(),
        )
        self.owner = User.objects.create_user(username="teamowner", password="password123")
        self.other_user = User.objects.create_user(username="viewer", password="password123")
        self.team = Team.objects.create(
            event=self.event,
            name="InspectTeam",
            invite_code="SECURE_INVITE_12345",
        )
        TeamMembership.objects.create(team=self.team, user=self.owner)

    def test_get_join_does_not_mutate_state_unauthenticated(self):
        """Unauthenticated GET on invite URL does not create any membership."""
        count_before = TeamMembership.objects.count()
        url = reverse("teams:join", args=[self.team.invite_code])

        response1 = self.client.get(url)
        self.assertEqual(response1.status_code, 200)
        self.assertEqual(TeamMembership.objects.count(), count_before)

        # Repeated GET (e.g. crawler/link prefetch)
        response2 = self.client.get(url)
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(TeamMembership.objects.count(), count_before)

    def test_get_join_does_not_mutate_state_authenticated(self):
        """Authenticated GET on invite URL does not create any membership."""
        self.client.force_login(self.other_user)
        count_before = TeamMembership.objects.count()
        url = reverse("teams:join", args=[self.team.invite_code])

        response1 = self.client.get(url)
        self.assertEqual(response1.status_code, 200)
        self.assertContains(response1, "InspectTeam")
        self.assertEqual(TeamMembership.objects.count(), count_before)

        response2 = self.client.get(url)
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(TeamMembership.objects.count(), count_before)

    def test_get_invalid_invite_code_returns_404(self):
        """GET with unknown invite_code returns 404 without side effects."""
        count_before = TeamMembership.objects.count()
        response = self.client.get(reverse("teams:join", args=["NONEXISTENT_CODE"]))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(TeamMembership.objects.count(), count_before)


class TeamJoinPostTest(TestCase):
    """Tests for POST /teams/join/<invite_code>/ membership creation and race-safety."""

    def setUp(self):
        self.client = Client()
        self.event = Event.objects.create(
            name="Join Event",
            submissions_close=timezone.now(),
        )
        self.creator = User.objects.create_user(username="creator2", password="password123")
        self.joiner = User.objects.create_user(username="joiner", password="password123")
        self.team = Team.objects.create(
            event=self.event,
            name="JoinableTeam",
            invite_code="JOIN_CODE_98765",
        )
        TeamMembership.objects.create(team=self.team, user=self.creator)

    def test_unauthenticated_post_redirects_to_login(self):
        """Unauthenticated POST to join URL redirects to login without creating membership."""
        count_before = TeamMembership.objects.count()
        url = reverse("teams:join", args=[self.team.invite_code])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
        self.assertEqual(TeamMembership.objects.count(), count_before)

    def test_authenticated_post_joins_team(self):
        """Authenticated POST creates a new TeamMembership."""
        self.client.force_login(self.joiner)
        count_before = TeamMembership.objects.count()
        url = reverse("teams:join", args=[self.team.invite_code])

        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("teams:detail", args=[self.team.id]))

        self.assertEqual(TeamMembership.objects.count(), count_before + 1)
        self.assertTrue(
            TeamMembership.objects.filter(team=self.team, user=self.joiner).exists()
        )

    def test_repeated_post_is_idempotent_and_safe(self):
        """Repeated POST (simulating retry or double-click) does not duplicate membership."""
        self.client.force_login(self.joiner)
        url = reverse("teams:join", args=[self.team.invite_code])

        # First join
        response1 = self.client.post(url)
        self.assertEqual(response1.status_code, 302)
        count_after_first = TeamMembership.objects.count()

        # Second join (retry)
        response2 = self.client.post(url)
        self.assertEqual(response2.status_code, 302)
        self.assertEqual(
            TeamMembership.objects.count(),
            count_after_first,
            "Repeated POST created duplicate membership!",
        )

    def test_post_invalid_invite_code_returns_404(self):
        """POST with invalid invite_code returns 404 without side effects."""
        self.client.force_login(self.joiner)
        count_before = TeamMembership.objects.count()
        response = self.client.post(reverse("teams:join", args=["UNKNOWN_INVITE_XYZ"]))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(TeamMembership.objects.count(), count_before)
