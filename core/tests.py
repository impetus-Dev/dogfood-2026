from io import StringIO
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.utils import timezone

from accounts.models import Profile
from events.models import Event, Track
from judging.models import JudgeAssignment, RubricCriterion, Score
from projects.models import Project
from teams.models import Team

User = get_user_model()


class CoreCommandTest(TestCase):
    def test_seed_fixtures_command(self):
        out = StringIO()
        call_command("seed_fixtures", stdout=out)
        output = out.getvalue()
        self.assertIn("seed_fixtures", output)


class LoginAndOrganizerDashboardTest(TestCase):
    """
    Focused tests for Phase 2: Login experience and Organizer dashboard.
    """

    def setUp(self):
        self.client = Client()

        # Seed Event
        self.event = Event.objects.create(
            name="Sample Hack 2026",
            submissions_close=timezone.now() + timezone.timedelta(days=2),
            voting_mode="authenticated",
        )
        self.track = Track.objects.create(name="AI & Algorithms", event=self.event)

        # Organizer User
        self.organizer = User.objects.create_user(
            username="test_organizer", password="secure_password_1"
        )
        Profile.objects.create(user=self.organizer, role="organizer")

        # Admin User
        self.admin_user = User.objects.create_user(
            username="test_admin", password="secure_password_2", is_staff=True
        )
        Profile.objects.create(user=self.admin_user, role="admin")

        # Judge User
        self.judge = User.objects.create_user(
            username="test_judge", password="secure_password_3"
        )
        Profile.objects.create(user=self.judge, role="judge")

        # Participant User & Team
        self.participant = User.objects.create_user(
            username="test_participant", password="secure_password_4"
        )
        Profile.objects.create(user=self.participant, role="participant")

        self.team = Team.objects.create(
            name="CyberTeam", event=self.event, invite_code="inv12345"
        )
        self.project = Project.objects.create(
            team=self.team,
            track=self.track,
            title="Cyber Project",
            summary="Next-gen cybersecurity analyzer",
            repo_url="https://github.com/cyber/analyzer",
            status="submitted",
            submitted_at=timezone.now(),
        )

        # Rubric & Judging
        self.criterion = RubricCriterion.objects.create(
            event=self.event, name="Innovation", weight=1.5
        )
        self.assignment = JudgeAssignment.objects.create(
            judge=self.judge, project=self.project
        )
        self.score = Score.objects.create(
            judge=self.judge,
            project=self.project,
            criteria_scores={"Innovation": 9},
            comment="Excellent work!",
        )

    # --- Login Tests ---

    def test_anonymous_access_dashboard_redirects_to_login(self):
        """Unauthenticated user accessing /dashboard/ is redirected to /accounts/login/."""
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_login_redirects_to_dashboard(self):
        """Valid credentials log the user in and redirect to /dashboard/ (never to /accounts/whoami/)."""
        response = self.client.post(
            "/accounts/login/",
            {"username": "test_organizer", "password": "secure_password_1"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/dashboard/")

    def test_authenticated_user_visiting_login_redirects_to_dashboard(self):
        """An already-authenticated user visiting /accounts/login/ is redirected to /dashboard/."""
        self.client.force_login(self.organizer)
        response = self.client.get("/accounts/login/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/dashboard/")

    def test_login_invalid_credentials_shows_error(self):
        """Invalid credentials stay on login page with error message."""
        response = self.client.post(
            "/accounts/login/",
            {"username": "test_organizer", "password": "wrong_password"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid credentials")

    def test_whoami_still_returns_technical_json(self):
        """Technical verification endpoint /accounts/whoami/ remains fully functional."""
        self.client.force_login(self.organizer)
        response = self.client.get("/accounts/whoami/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["authenticated"])
        self.assertEqual(data["username"], "test_organizer")
        self.assertEqual(data["role"], "organizer")

    # --- Organizer Dashboard Tests ---

    def test_organizer_dashboard_loads_with_real_metrics(self):
        """Organizer dashboard loads 200 and displays real model counts."""
        self.client.force_login(self.organizer)
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 200)

        # Check template & context
        self.assertTemplateUsed(response, "dashboard/organizer.html")
        self.assertEqual(response.context["total_projects"], 1)
        self.assertEqual(response.context["submitted_projects"], 1)
        self.assertEqual(response.context["total_teams"], 1)
        self.assertEqual(response.context["total_judges"], 1)
        self.assertEqual(response.context["total_assignments"], 1)
        self.assertEqual(response.context["total_scores"], 1)

        # Check content renders real values
        self.assertContains(response, "Sample Hack 2026")
        self.assertContains(response, "Cyber Project")
        self.assertContains(response, "CyberTeam")
        self.assertContains(response, "Control Center")

    def test_admin_dashboard_loads_organizer_view(self):
        """Admin user also receives the organizer control center."""
        self.client.force_login(self.admin_user)
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/organizer.html")

    def test_participant_isolated_from_organizer_dashboard_content(self):
        """Participant visiting dashboard does not see the organizer control center template."""
        self.client.force_login(self.participant)
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateNotUsed(response, "dashboard/organizer.html")
        self.assertTemplateUsed(response, "dashboard/participant.html")
