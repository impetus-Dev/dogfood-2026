import os
import sys
import math
import csv
from io import StringIO
from datetime import datetime, timezone

import django
from django.conf import settings

# Configure minimal Django settings
if not settings.configured:
    settings.configure(
        DEBUG=True,
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": ":memory:",
            }
        },
        INSTALLED_APPS=[
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "accounts",
            "events",
            "projects",
            "judging",
        ],
        ROOT_URLCONF="judging.urls",
        SECRET_KEY="test-secret-key-dogfood-t2",
        MIDDLEWARE=[],
    )
    django.setup()

from django.core.management import call_command
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.urls import resolve, reverse

from accounts.models import Profile
from events.models import Event, Track
from projects.models import Project
from judging.models import RubricCriterion, JudgeAssignment, Score
from judging.normalization import normalize_scores, compute_raw_score, RankedProjects
from judging.views import JudgeScoresView, ExportCSVView

User = get_user_model()


class T2TestCase(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        # Users with profiles
        self.u_visitor = User.objects.create_user(username="visitor", password="p")
        Profile.objects.create(user=self.u_visitor, role="visitor")

        self.u_participant = User.objects.create_user(username="participant", password="p")
        Profile.objects.create(user=self.u_participant, role="participant")

        self.u_judge1 = User.objects.create_user(username="judge1", password="p")
        Profile.objects.create(user=self.u_judge1, role="judge")

        self.u_judge2 = User.objects.create_user(username="judge2", password="p")
        Profile.objects.create(user=self.u_judge2, role="judge")

        self.u_organizer = User.objects.create_user(username="organizer", password="p")
        Profile.objects.create(user=self.u_organizer, role="organizer")

        self.u_admin = User.objects.create_user(username="admin", password="p")
        Profile.objects.create(user=self.u_admin, role="admin")

        # Event & Tracks
        self.event = Event.objects.create(name="Dogfood Hackathon 2026")
        self.track = Track.objects.create(event=self.event, name="Web3 & Infra")

        # Rubric criteria
        self.crit_tech = RubricCriterion.objects.create(event=self.event, name="technical", weight=1.0)
        self.crit_design = RubricCriterion.objects.create(event=self.event, name="design", weight=2.0)

        # Projects
        self.proj_a = Project.objects.create(
            title="Project A",
            track=self.track,
            submitted_at=datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc),
        )
        self.proj_b = Project.objects.create(
            title="Project B",
            track=self.track,
            submitted_at=datetime(2026, 9, 26, 13, 0, 0, tzinfo=timezone.utc),
        )
        self.proj_c = Project.objects.create(
            title="Project C",
            track=self.track,
            submitted_at=datetime(2026, 9, 26, 14, 0, 0, tzinfo=timezone.utc),
        )

    def test_normalization_basic_and_zero_variance(self):
        """
        Test Z-score normalization with varying scores and zero-variance safety.
        """
        # Judge 1 gives different scores:
        # proj_a: tech=10, design=10 -> raw = 10*1 + 10*2 = 30
        # proj_b: tech=5,  design=5  -> raw = 5*1 + 5*2 = 15
        # proj_c: tech=0,  design=0  -> raw = 0
        # Mean = (30 + 15 + 0) / 3 = 15.0
        # Variance = ((30-15)^2 + (15-15)^2 + (0-15)^2) / 3 = (225 + 0 + 225)/3 = 150
        # Std Dev = sqrt(150) ~= 12.2474487
        Score.objects.create(
            judge=self.u_judge1,
            project=self.proj_a,
            criteria_scores={"technical": 10, "design": 10},
            comment="Awesome A",
        )
        Score.objects.create(
            judge=self.u_judge1,
            project=self.proj_b,
            criteria_scores={"technical": 5, "design": 5},
            comment="Good B",
        )
        Score.objects.create(
            judge=self.u_judge1,
            project=self.proj_c,
            criteria_scores={"technical": 0, "design": 0},
            comment="Poor C",
        )

        # Judge 2 gives identical scores to all projects (zero variance):
        # proj_a: tech=8, design=8 -> raw = 24
        # proj_b: tech=8, design=8 -> raw = 24
        # proj_c: tech=8, design=8 -> raw = 24
        # Mean = 24, std_dev = 0 < 1e-4 -> std_dev treated as 1.0
        # Z = (24 - 24) / (1.0 + epsilon) = 0.0 for all!
        Score.objects.create(
            judge=self.u_judge2,
            project=self.proj_a,
            criteria_scores={"technical": 8, "design": 8},
            comment="J2 A",
        )
        Score.objects.create(
            judge=self.u_judge2,
            project=self.proj_b,
            criteria_scores={"technical": 8, "design": 8},
            comment="J2 B",
        )
        Score.objects.create(
            judge=self.u_judge2,
            project=self.proj_c,
            criteria_scores={"technical": 8, "design": 8},
            comment="J2 C",
        )

        rankings = normalize_scores(self.event)
        self.assertEqual(len(rankings), 3)

        # Project A should be ranked #1
        self.assertEqual(rankings[0]["project_id"], self.proj_a.id)
        self.assertEqual(rankings[0].rank, 1)

        # Project B should be ranked #2
        self.assertEqual(rankings[1]["project_id"], self.proj_b.id)
        self.assertEqual(rankings[1].rank, 2)

        # Project C should be ranked #3
        self.assertEqual(rankings[2]["project_id"], self.proj_c.id)
        self.assertEqual(rankings[2].rank, 3)

        # Check that Judge 2's Z-scores are 0.0 due to zero-variance safety
        std1 = math.sqrt(150.0)
        expected_z_a1 = (30.0 - 15.0) / (std1 + 1e-9)
        expected_z_a2 = 0.0
        expected_avg_a = (expected_z_a1 + expected_z_a2) / 2.0
        self.assertAlmostEqual(rankings[0]["normalized_score"], expected_avg_a, places=5)

        # Check mapping behavior
        mapping = rankings.to_dict()
        self.assertIn(self.proj_a.id, mapping)
        self.assertEqual(mapping[self.proj_a.id], rankings[0]["normalized_score"])

    def test_single_project_judge_zero_variance(self):
        """
        If a judge reviews only 1 project, std_dev is 0 < 1e-4, safe division must apply.
        """
        Score.objects.create(
            judge=self.u_judge1,
            project=self.proj_a,
            criteria_scores={"technical": 10},
            comment="Only scored 1",
        )
        rankings = normalize_scores(self.event)
        self.assertEqual(len(rankings), 1)
        self.assertAlmostEqual(rankings[0]["normalized_score"], 0.0, places=5)

    def test_judge_scores_view_auth_and_roles(self):
        """
        Verify JudgeScoresView:
          - 401 unauthenticated
          - 403 visitor / participant
          - 200 judge viewing own scores
          - 403 judge viewing another judge (Backend Role Isolation)
          - 200 organizer viewing another judge
          - 200 admin viewing another judge
          - 404 judge not found
        """
        view = JudgeScoresView.as_view()

        # Score for judge1
        Score.objects.create(
            judge=self.u_judge1,
            project=self.proj_a,
            criteria_scores={"technical": 9, "design": 8},
            comment="Impressive work",
        )

        # 1. Unauthenticated -> 401
        req = self.factory.get("/api/judge/scores/")
        from django.contrib.auth.models import AnonymousUser
        req.user = AnonymousUser()
        resp = view(req)
        self.assertEqual(resp.status_code, 401)

        # 2. Visitor -> 403
        req = self.factory.get("/api/judge/scores/")
        req.user = self.u_visitor
        resp = view(req)
        self.assertEqual(resp.status_code, 403)

        # 3. Participant -> 403
        req = self.factory.get("/api/judge/scores/")
        req.user = self.u_participant
        resp = view(req)
        self.assertEqual(resp.status_code, 403)

        # 4. Judge1 viewing self (no param) -> 200
        req = self.factory.get("/api/judge/scores/")
        req.user = self.u_judge1
        resp = view(req)
        self.assertEqual(resp.status_code, 200)
        import json
        data = json.loads(resp.content.decode("utf-8"))
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["project_id"], self.proj_a.id)
        self.assertEqual(data[0]["criteria_scores"], {"technical": 9, "design": 8})
        self.assertEqual(data[0]["comment"], "Impressive work")

        # 5. Judge1 viewing self with ?judge=<id> or ?judge=<username> -> 200
        req = self.factory.get(f"/api/judge/scores/?judge={self.u_judge1.id}")
        req.user = self.u_judge1
        resp = view(req)
        self.assertEqual(resp.status_code, 200)

        req = self.factory.get("/api/judge/scores/?judge=judge1")
        req.user = self.u_judge1
        resp = view(req)
        self.assertEqual(resp.status_code, 200)

        # 6. BACKEND ROLE ISOLATION: Judge1 viewing Judge2 -> 403!
        req = self.factory.get(f"/api/judge/scores/?judge={self.u_judge2.id}")
        req.user = self.u_judge1
        resp = view(req)
        self.assertEqual(resp.status_code, 403)

        req = self.factory.get("/api/judge/scores/?judge=judge2")
        req.user = self.u_judge1
        resp = view(req)
        self.assertEqual(resp.status_code, 403)

        # 7. Organizer viewing Judge1 -> 200
        req = self.factory.get(f"/api/judge/scores/?judge={self.u_judge1.id}")
        req.user = self.u_organizer
        resp = view(req)
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content.decode("utf-8"))
        self.assertEqual(len(data), 1)

        # 8. Admin viewing Judge1 -> 200
        req = self.factory.get("/api/judge/scores/?judge=judge1")
        req.user = self.u_admin
        resp = view(req)
        self.assertEqual(resp.status_code, 200)

        # 9. Organizer viewing non-existent judge -> 404
        req = self.factory.get("/api/judge/scores/?judge=nonexistent_judge_999")
        req.user = self.u_organizer
        resp = view(req)
        self.assertEqual(resp.status_code, 404)

    def test_export_csv_view(self):
        """
        Verify ExportCSVView:
          - 401 unauthenticated
          - 403 unauthorized role
          - 200 organizer/admin
          - Content-Type: text/csv
          - Content-Disposition: attachment; filename="results.csv"
          - First line contains comma (',')
          - Columns: project_id,project_title,track,submitted_at,review_count
        """
        view = ExportCSVView.as_view()

        # Add scores: proj_a has 2 reviews, proj_b has 1, proj_c has 0
        Score.objects.create(judge=self.u_judge1, project=self.proj_a, criteria_scores={"t": 8})
        Score.objects.create(judge=self.u_judge2, project=self.proj_a, criteria_scores={"t": 7})
        Score.objects.create(judge=self.u_judge1, project=self.proj_b, criteria_scores={"t": 6})

        # 1. Unauthenticated -> 401
        from django.contrib.auth.models import AnonymousUser
        req = self.factory.get("/api/export.csv")
        req.user = AnonymousUser()
        resp = view(req)
        self.assertEqual(resp.status_code, 401)

        # 2. Judge / Participant -> 403
        req = self.factory.get("/api/export.csv")
        req.user = self.u_judge1
        resp = view(req)
        self.assertEqual(resp.status_code, 403)

        req.user = self.u_participant
        resp = view(req)
        self.assertEqual(resp.status_code, 403)

        # 3. Organizer -> 200
        req = self.factory.get("/api/export.csv")
        req.user = self.u_organizer
        resp = view(req)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])
        self.assertEqual(resp["Content-Disposition"], 'attachment; filename="results.csv"')

        # CRITICAL ACCEPTANCE REQUIREMENT: First line contains comma (',')
        content = resp.content.decode("utf-8")
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        self.assertTrue(len(lines) >= 4)  # 1 header + 3 projects
        self.assertIn(",", lines[0])

        reader = csv.reader(StringIO(content))
        rows = list(reader)
        self.assertEqual(rows[0], ["project_id", "project_title", "track", "submitted_at", "review_count"])

        # Check rows:
        row_map = {row[0]: row for row in rows[1:]}
        # proj_a should have review_count 2
        self.assertEqual(row_map[str(self.proj_a.id)][1], "Project A")
        self.assertEqual(row_map[str(self.proj_a.id)][2], "Web3 & Infra")
        self.assertEqual(row_map[str(self.proj_a.id)][4], "2")

        # proj_b should have review_count 1
        self.assertEqual(row_map[str(self.proj_b.id)][4], "1")

        # proj_c should have review_count 0
        self.assertEqual(row_map[str(self.proj_c.id)][4], "0")

    def test_urls_registered(self):
        """
        Verify URL routing matching .dogfood.toml
        """
        match_scores = resolve("/api/judge/scores/")
        self.assertEqual(match_scores.view_name, "judge_scores")

        match_csv = resolve("/api/export.csv")
        self.assertEqual(match_csv.view_name, "csv_export")

        self.assertEqual(reverse("judge_scores"), "/api/judge/scores/")
        self.assertEqual(reverse("csv_export"), "/api/export.csv")

    def test_normalization_edge_cases(self):
        """
        Extensive edge cases for normalization:
        - empty event / no ballots
        - criteria without explicit weights
        - integer/float criteria_scores
        - near-zero variance (< 1e-4)
        - as_dict and as_mapping flags
        - dictionary access on RankedProjects
        """
        empty_event = Event.objects.create(name="Empty Event")
        res_empty = normalize_scores(empty_event)
        self.assertEqual(len(res_empty), 0)
        self.assertEqual(res_empty.to_dict(), {})

        # Test near-zero variance (< 1e-4)
        # Score difference of 0.00001 -> std_dev < 1e-4 -> treated as 1.0
        Score.objects.all().delete()
        Score.objects.create(
            judge=self.u_judge1,
            project=self.proj_a,
            criteria_scores={"technical": 10.00000},
        )
        Score.objects.create(
            judge=self.u_judge1,
            project=self.proj_b,
            criteria_scores={"technical": 10.00001},
        )
        rankings = normalize_scores(self.event)
        self.assertEqual(len(rankings), 2)
        # Check std_dev was clamped to 1.0, so z-score difference is small (~0.00001)
        z_a = rankings.get(self.proj_a.id)["normalized_score"]
        z_b = rankings.get(self.proj_b.id)["normalized_score"]
        self.assertAlmostEqual(abs(z_a - z_b), 0.00001, places=4)

        # Test passing event as ID
        rankings_by_id = normalize_scores(self.event.id)
        self.assertEqual(len(rankings_by_id), 2)

        # Test as_dict=True
        dict_res = normalize_scores(self.event, as_dict=True)
        self.assertIsInstance(dict_res, dict)
        self.assertIn(self.proj_a.id, dict_res)

        # Test as_mapping=True
        map_res = normalize_scores(self.event, as_mapping=True)
        self.assertIsInstance(map_res, dict)
        self.assertIn(self.proj_a, map_res)

    def test_csv_export_special_characters_and_empty(self):
        """
        Test CSV export with commas in title and empty projects.
        """
        Score.objects.all().delete()
        Project.objects.all().delete()

        proj_special = Project.objects.create(
            title="AI, ML & Blockchain: A New Era",
            track=self.track,
        )

        view = ExportCSVView.as_view()
        req = self.factory.get("/api/export.csv")
        req.user = self.u_organizer
        resp = view(req)
        self.assertEqual(resp.status_code, 200)

        content = resp.content.decode("utf-8")
        reader = csv.reader(StringIO(content))
        rows = list(reader)
        self.assertEqual(len(rows), 2)  # Header + 1 project
        self.assertEqual(rows[0][0], "project_id")
        self.assertIn(",", content.splitlines()[0])
        self.assertEqual(rows[1][1], "AI, ML & Blockchain: A New Era")
        self.assertEqual(rows[1][4], "0")


if __name__ == "__main__":
    from django.db import connection
    tables = [Profile, Event, Track, Project, RubricCriterion, JudgeAssignment, Score]
    with connection.schema_editor() as schema_editor:
        for model in tables:
            try:
                schema_editor.create_model(model)
            except Exception:
                pass
    call_command("migrate", verbosity=0)
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(T2TestCase)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        sys.exit(1)
    print("ALL T2 TESTS PASSED SUCCESSFULLY!")
