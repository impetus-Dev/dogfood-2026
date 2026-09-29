from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone
from datetime import timedelta

from events.models import Event, Track
from teams.models import Team, TeamMembership
from projects.models import Project
from judging.models import RubricCriterion, JudgeAssignment, Score
from voting.models import VotingToken
from t4.models import JudgeRecord

User = get_user_model()


class EmbedGalleryWidgetTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.now = timezone.now()

        self.event = Event.objects.create(
            name="Widget Hackathon 2026",
            external_id="widget_evt_01",
            submissions_close=self.now + timedelta(days=2),
            voting_close=self.now + timedelta(days=3),
        )

        self.track1 = Track.objects.create(
            event=self.event,
            name="Developer Tools",
            external_id="trk_dev_01",
        )
        self.track2 = Track.objects.create(
            event=self.event,
            name="Climate Tech",
            external_id="trk_clim_02",
        )

        self.team = Team.objects.create(
            event=self.event,
            name="Solar Pioneers",
            invite_code="SECRET_INVITE_CODE_98765",
        )

        self.user = User.objects.create_user(
            username="participant1",
            email="p1@example.com",
            password="secretpassword123",
        )
        TeamMembership.objects.create(
            team=self.team,
            user=self.user,
        )

        self.project1 = Project.objects.create(
            team=self.team,
            track=self.track1,
            title="Solar Optimizer AI",
            summary="A high-performance algorithmic energy optimizer.",
            repo_url="https://github.com/example/solar-ai",
            status="submitted",
        )
        self.project2 = Project.objects.create(
            team=self.team,
            track=self.track2,
            title="Carbon Tracker CLI",
            summary="CLI tool to trace emissions in real-time.",
            repo_url="https://github.com/example/carbon-cli",
            status="draft",
        )

    def test_embed_gallery_renders_valid_event_with_project_data(self):
        """Valid event returns 200 with public project information."""
        resp = self.client.get(f"/embed/gallery/{self.event.id}/")
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")

        self.assertIn("Widget Hackathon 2026", content)
        self.assertIn("Solar Optimizer AI", content)
        self.assertIn("A high-performance algorithmic energy optimizer", content)
        self.assertIn("Developer Tools", content)
        self.assertIn("Solar Pioneers", content)
        self.assertIn("https://github.com/example/solar-ai", content)

    def test_embed_gallery_renders_via_external_id(self):
        """Event can be embedded using its external_id string."""
        resp = self.client.get("/embed/gallery/widget_evt_01/")
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")
        self.assertIn("Widget Hackathon 2026", content)
        self.assertIn("Solar Optimizer AI", content)

    def test_embed_gallery_invalid_event_returns_404(self):
        """Non-existent event ID correctly raises 404."""
        resp = self.client.get("/embed/gallery/999999/")
        self.assertEqual(resp.status_code, 404)

    def test_embed_gallery_framing_headers_permit_embedding(self):
        """
        Embed route must permit framing: X-Frame-Options is relaxed (not DENY)
        and Content-Security-Policy frame-ancestors is unrestricted.
        """
        resp = self.client.get(f"/embed/gallery/{self.event.id}/")
        self.assertEqual(resp.status_code, 200)

        # X-Frame-Options must NOT be DENY
        x_frame_options = resp.headers.get("X-Frame-Options")
        self.assertIsNone(x_frame_options, "X-Frame-Options must be absent/relaxed on embed route")

        # CSP frame-ancestors must allow embedding
        csp = resp.headers.get("Content-Security-Policy", "")
        self.assertIn("frame-ancestors *", csp)

    def test_global_clickjacking_protection_preserved_on_standard_routes(self):
        """Standard application routes must retain X-Frame-Options: DENY."""
        resp = self.client.get("/projects/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.headers.get("X-Frame-Options"),
            "DENY",
            "Non-embed routes must strictly retain X-Frame-Options: DENY",
        )

    def test_embed_gallery_leak_prevention(self):
        """
        Embed route must NEVER expose:
        - Team invite codes
        - Judge scores or private evaluation notes
        - Voting tokens
        - User passwords or password hashes
        - Cryptographic signing keys
        """
        # Create sensitive judge records & scores
        judge_user = User.objects.create_user(
            username="judge_secret",
            email="judge@example.com",
            password="judgepassword456",
        )
        criterion = RubricCriterion.objects.create(
            event=self.event,
            name="Secret Innovation Metric",
            weight=1.5,
        )
        assignment = JudgeAssignment.objects.create(
            judge=judge_user,
            project=self.project1,
        )
        Score.objects.create(
            judge=judge_user,
            project=self.project1,
            criteria_scores={"criterion_1": 98.5},
            comment="Top secret judge evaluation note",
        )

        # Create voting token
        token = VotingToken.objects.create(
            event=self.event,
            token="SENSITIVE_VOTING_TOKEN_7777",
        )

        resp = self.client.get(f"/embed/gallery/{self.event.id}/")
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")

        # Strictly verify sensitive strings are ABSENT
        self.assertNotIn("SECRET_INVITE_CODE_98765", content)
        self.assertNotIn("SENSITIVE_VOTING_TOKEN_7777", content)
        self.assertNotIn("Secret Innovation Metric", content)
        self.assertNotIn("judge_secret", content)
        self.assertNotIn("98.5", content)
        self.assertNotIn("secretpassword123", content)
        self.assertNotIn("judgepassword456", content)

    def test_embed_script_helper(self):
        """The /embed/gallery.js helper serves JavaScript with iframe auto-generation."""
        resp = self.client.get("/embed/gallery.js")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("Content-Type"), "application/javascript")
        content = resp.content.decode("utf-8")
        self.assertIn("document.querySelectorAll('script[data-event]')", content)
        self.assertIn("iframe.src", content)
        self.assertIsNone(resp.headers.get("X-Frame-Options"))

    def test_embed_gallery_filtering_and_search(self):
        """Filtering by track and search by keyword narrows project list."""
        # Search query
        resp_q = self.client.get(f"/embed/gallery/{self.event.id}/?q=Carbon")
        self.assertEqual(resp_q.status_code, 200)
        content_q = resp_q.content.decode("utf-8")
        self.assertIn("Carbon Tracker CLI", content_q)
        self.assertNotIn("Solar Optimizer AI", content_q)

        # Track filter
        resp_t = self.client.get(f"/embed/gallery/{self.event.id}/?track={self.track1.id}")
        self.assertEqual(resp_t.status_code, 200)
        content_t = resp_t.content.decode("utf-8")
        self.assertIn("Solar Optimizer AI", content_t)
        self.assertNotIn("Carbon Tracker CLI", content_t)
