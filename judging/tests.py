import csv
from io import StringIO
import math
from datetime import datetime, timezone

from django.contrib.auth.models import AnonymousUser, User
from django.test import RequestFactory, TestCase
from django.urls import resolve, reverse

from accounts.models import Profile
from events.models import Event, Track
from projects.models import Project
from teams.models import Team
from judging.models import JudgeAssignment, RubricCriterion, Score
from judging.normalization import (
    RankedProjects,
    compute_raw_score,
    normalize_scores,
)
from judging.views import ExportCSVView, JudgeScoresView


class T2JudgingTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        # Users with profiles
        self.u_visitor = User.objects.create_user(username="visitor", password="p")
        Profile.objects.create(user=self.u_visitor, role="visitor")

        self.u_participant = User.objects.create_user(username="participant", password="p")
        Profile.objects.create(user=self.u_participant, role="participant")

        self.u_judge_a = User.objects.create_user(username="judge_a", password="p")
        Profile.objects.create(user=self.u_judge_a, role="judge")

        self.u_judge_b = User.objects.create_user(username="judge_b", password="p")
        Profile.objects.create(user=self.u_judge_b, role="judge")

        self.u_organizer = User.objects.create_user(username="organizer", password="p")
        Profile.objects.create(user=self.u_organizer, role="organizer")

        self.u_admin = User.objects.create_user(username="admin", password="p")
        Profile.objects.create(user=self.u_admin, role="admin")

        # Event, Track, Team
        self.event = Event.objects.create(
            name="Dogfood Hackathon 2026",
            submissions_close=datetime(2026, 9, 27, 18, 0, 0, tzinfo=timezone.utc),
        )
        self.track = Track.objects.create(event=self.event, name="Web3 & Infra")
        self.team = Team.objects.create(name="Team Alpha", event=self.event)

        # Rubric criteria
        self.crit_tech = RubricCriterion.objects.create(event=self.event, name="technical", weight=1.0)
        self.crit_design = RubricCriterion.objects.create(event=self.event, name="design", weight=2.0)

        # Projects
        self.proj_a = Project.objects.create(
            title="Project A",
            team=self.team,
            track=self.track,
            summary="A revolutionary project",
            repo_url="https://github.com/test/a",
            submitted_at=datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc),
        )
        self.proj_b = Project.objects.create(
            title="Project B",
            team=self.team,
            track=self.track,
            summary="An innovative project",
            repo_url="https://github.com/test/b",
            submitted_at=datetime(2026, 9, 26, 13, 0, 0, tzinfo=timezone.utc),
        )
        self.proj_c = Project.objects.create(
            title="Project C",
            team=self.team,
            track=self.track,
            summary="A creative project",
            repo_url="https://github.com/test/c",
            submitted_at=datetime(2026, 9, 26, 14, 0, 0, tzinfo=timezone.utc),
        )

    # -------------------------------------------------------------------------
    # Assertion 1: Judge sees own scores
    # -------------------------------------------------------------------------
    def test_assertion_1_judge_sees_own_scores(self):
        Score.objects.create(
            judge=self.u_judge_a,
            project=self.proj_a,
            criteria_scores={"technical": 9, "design": 8},
            comment="Strong architecture",
        )
        view = JudgeScoresView.as_view()

        # Direct access without query param
        req = self.factory.get("/api/judge/scores/")
        req.user = self.u_judge_a
        resp = view(req)
        self.assertEqual(resp.status_code, 200)

        import json
        data = json.loads(resp.content.decode("utf-8"))
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["project_id"], self.proj_a.id)
        self.assertEqual(data[0]["project_title"], "Project A")
        self.assertEqual(data[0]["criteria_scores"], {"technical": 9, "design": 8})
        self.assertEqual(data[0]["comment"], "Strong architecture")

        # Access with own username
        req = self.factory.get("/api/judge/scores/?judge=judge_a")
        req.user = self.u_judge_a
        resp = view(req)
        self.assertEqual(resp.status_code, 200)

        # Access with own user ID
        req = self.factory.get(f"/api/judge/scores/?judge={self.u_judge_a.id}")
        req.user = self.u_judge_a
        resp = view(req)
        self.assertEqual(resp.status_code, 200)

    # -------------------------------------------------------------------------
    # Assertion 2: Judge cannot see peer scores (Backend Role Isolation)
    # -------------------------------------------------------------------------
    def test_assertion_2_judge_cannot_see_peer_scores(self):
        Score.objects.create(
            judge=self.u_judge_a,
            project=self.proj_a,
            criteria_scores={"technical": 9, "design": 8},
            comment="Judge A review",
        )
        view = JudgeScoresView.as_view()

        # judge_b tries to query judge_a's scores by username -> 403
        req = self.factory.get("/api/judge/scores/?judge=judge_a")
        req.user = self.u_judge_b
        resp = view(req)
        self.assertEqual(resp.status_code, 403)

        # judge_b tries to query judge_a's scores by user id -> 403
        req = self.factory.get(f"/api/judge/scores/?judge={self.u_judge_a.id}")
        req.user = self.u_judge_b
        resp = view(req)
        self.assertEqual(resp.status_code, 403)

        # In contrast, organizer and admin CAN view peer scores
        req_org = self.factory.get("/api/judge/scores/?judge=judge_a")
        req_org.user = self.u_organizer
        resp_org = view(req_org)
        self.assertEqual(resp_org.status_code, 200)

        req_adm = self.factory.get("/api/judge/scores/?judge=judge_a")
        req_adm.user = self.u_admin
        resp_adm = view(req_adm)
        self.assertEqual(resp_adm.status_code, 200)

    # -------------------------------------------------------------------------
    # Assertion 3: Participant / Visitor / Unauthenticated blocked
    # -------------------------------------------------------------------------
    def test_assertion_3_participant_blocked(self):
        view = JudgeScoresView.as_view()

        # Unauthenticated -> 401
        req_anon = self.factory.get("/api/judge/scores/")
        req_anon.user = AnonymousUser()
        resp_anon = view(req_anon)
        self.assertEqual(resp_anon.status_code, 401)

        # Participant -> 403
        req_part = self.factory.get("/api/judge/scores/")
        req_part.user = self.u_participant
        resp_part = view(req_part)
        self.assertEqual(resp_part.status_code, 403)

        # Visitor -> 403
        req_vis = self.factory.get("/api/judge/scores/")
        req_vis.user = self.u_visitor
        resp_vis = view(req_vis)
        self.assertEqual(resp_vis.status_code, 403)

    # -------------------------------------------------------------------------
    # Assertion 4: CSV Export works
    # -------------------------------------------------------------------------
    def test_assertion_4_csv_export_works(self):
        view = ExportCSVView.as_view()

        # Create scores
        Score.objects.create(judge=self.u_judge_a, project=self.proj_a, criteria_scores={"technical": 10})
        Score.objects.create(judge=self.u_judge_b, project=self.proj_a, criteria_scores={"technical": 8})
        Score.objects.create(judge=self.u_judge_a, project=self.proj_b, criteria_scores={"technical": 7})

        # Unauthenticated -> 401
        req_anon = self.factory.get("/api/export.csv")
        req_anon.user = AnonymousUser()
        self.assertEqual(view(req_anon).status_code, 401)

        # Judge / Participant -> 403
        req_judge = self.factory.get("/api/export.csv")
        req_judge.user = self.u_judge_a
        self.assertEqual(view(req_judge).status_code, 403)

        req_part = self.factory.get("/api/export.csv")
        req_part.user = self.u_participant
        self.assertEqual(view(req_part).status_code, 403)

        # Organizer -> 200
        req_org = self.factory.get("/api/export.csv")
        req_org.user = self.u_organizer
        resp_org = view(req_org)
        self.assertEqual(resp_org.status_code, 200)

        # Content headers
        self.assertIn("text/csv", resp_org["Content-Type"])
        self.assertEqual(resp_org["Content-Disposition"], 'attachment; filename="results.csv"')

        # CRITICAL ACCEPTANCE REQUIREMENT: First line contains comma
        content = resp_org.content.decode("utf-8")
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        self.assertTrue(len(lines) >= 4)  # 1 header + 3 projects
        self.assertIn(",", lines[0])

        reader = csv.reader(StringIO(content))
        rows = list(reader)
        self.assertEqual(rows[0], ["project_id", "project_title", "track", "submitted_at", "review_count"])

        # Check rows
        row_map = {row[0]: row for row in rows[1:]}
        self.assertEqual(row_map[str(self.proj_a.id)][1], "Project A")
        self.assertEqual(row_map[str(self.proj_a.id)][2], "Web3 & Infra")
        self.assertEqual(row_map[str(self.proj_a.id)][4], "2")
        self.assertEqual(row_map[str(self.proj_b.id)][4], "1")
        self.assertEqual(row_map[str(self.proj_c.id)][4], "0")

    # -------------------------------------------------------------------------
    # Normalization Tests
    # -------------------------------------------------------------------------
    def test_normalization_engine(self):
        # Judge A gives different scores:
        # proj_a: tech=10, design=10 -> 10*1 + 10*2 = 30
        # proj_b: tech=5,  design=5  -> 5*1 + 5*2 = 15
        # proj_c: tech=0,  design=0  -> 0
        # mean=15.0, var=150.0, std_dev=sqrt(150) ~= 12.2474
        Score.objects.create(
            judge=self.u_judge_a,
            project=self.proj_a,
            criteria_scores={"technical": 10, "design": 10},
        )
        Score.objects.create(
            judge=self.u_judge_a,
            project=self.proj_b,
            criteria_scores={"technical": 5, "design": 5},
        )
        Score.objects.create(
            judge=self.u_judge_a,
            project=self.proj_c,
            criteria_scores={"technical": 0, "design": 0},
        )

        # Judge B gives identical scores (zero variance safety):
        # tech=7, design=7 for all projects -> std_dev=0.0 < 1e-4 -> std_dev=1.0 -> Z=0.0
        Score.objects.create(
            judge=self.u_judge_b,
            project=self.proj_a,
            criteria_scores={"technical": 7, "design": 7},
        )
        Score.objects.create(
            judge=self.u_judge_b,
            project=self.proj_b,
            criteria_scores={"technical": 7, "design": 7},
        )
        Score.objects.create(
            judge=self.u_judge_b,
            project=self.proj_c,
            criteria_scores={"technical": 7, "design": 7},
        )

        rankings = normalize_scores(self.event)
        self.assertEqual(len(rankings), 3)

        # Ranking order: Proj A > Proj B > Proj C
        self.assertEqual(rankings[0]["project_id"], self.proj_a.id)
        self.assertEqual(rankings[1]["project_id"], self.proj_b.id)
        self.assertEqual(rankings[2]["project_id"], self.proj_c.id)

        # Verify math
        std_a = math.sqrt(150.0)
        expected_z_proj_a = ((30.0 - 15.0) / (std_a + 1e-9) + 0.0) / 2.0
        self.assertAlmostEqual(rankings[0]["normalized_score"], expected_z_proj_a, places=5)

    def test_url_reversal(self):
        self.assertEqual(reverse("judge_scores"), "/api/judge/scores/")
        self.assertEqual(reverse("csv_export"), "/api/export.csv")
        self.assertEqual(resolve("/api/judge/scores/").view_name, "judge_scores")
        self.assertEqual(resolve("/api/export.csv").view_name, "csv_export")
