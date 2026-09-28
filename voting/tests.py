"""
T3 Phase 2 — Voting endpoint and ballot ordering tests.

All tests run against PostgreSQL via Docker Compose.
Phase 1 model tests are preserved at the end of this file.
"""
import hashlib
import random
import threading
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from events.models import Event, Track
from projects.models import Project
from teams.models import Team, TeamMembership
from voting.models import Comment, Vote, VotingToken


# ===========================================================================
# Helpers
# ===========================================================================

def _make_event(name="Hackathon 2026", voting_mode="authenticated", **kw):
    now = timezone.now()
    return Event.objects.create(
        name=name,
        submissions_close=kw.pop("submissions_close", now + timedelta(days=1)),
        voting_close=kw.pop("voting_close", now + timedelta(days=2)),
        voting_mode=voting_mode,
        **kw,
    )


def _make_track(event, name="General Track"):
    return Track.objects.create(event=event, name=name)


def _make_team(event, name="Alpha Team", invite_code=None):
    import secrets
    return Team.objects.create(
        event=event,
        name=name,
        invite_code=invite_code or secrets.token_urlsafe(16),
    )


def _make_project(team, track, title="Project", status="submitted", **kw):
    now = timezone.now()
    return Project.objects.create(
        team=team,
        track=track,
        title=title,
        summary=kw.pop("summary", f"Summary for {title}"),
        repo_url=kw.pop("repo_url", f"https://example.com/{title.lower().replace(' ', '-')}"),
        status=status,
        submitted_at=now if status == "submitted" else None,
        **kw,
    )


def _make_user(username="voter", **kw):
    return User.objects.create_user(
        username=username,
        email=kw.pop("email", f"{username}@example.com"),
        password=kw.pop("password", "password123"),
        **kw,
    )


def _make_token(event, email="tokenvoter@example.com", token_str=None):
    import secrets
    return VotingToken.objects.create(
        event=event,
        email=email,
        token=token_str or secrets.token_urlsafe(32),
    )


# ===========================================================================
# AUTHENTICATED VOTING TESTS (1-9)
# ===========================================================================

class AuthenticatedVotingTests(TestCase):
    """Tests 1-9: Authenticated voting endpoint."""

    def setUp(self):
        self.event = _make_event(voting_mode="authenticated")
        self.track = _make_track(self.event)
        self.team = _make_team(self.event)
        self.project = _make_project(self.team, self.track, title="Project A")
        self.project_b = _make_project(self.team, self.track, title="Project B")
        self.user = _make_user("authed_voter")
        self.client = APIClient()
        self.client.force_login(self.user)

    # 1. Authenticated voter can cast one valid vote (201).
    def test_01_authenticated_vote_success(self):
        resp = self.client.post(
            "/api/vote/",
            {"event": self.event.pk, "project": self.project.pk},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["event"], self.event.pk)
        self.assertEqual(data["project"], self.project.pk)
        self.assertIn("vote_id", data)

    # 2. Vote has correct event, project, voter, NULL voting_token.
    def test_02_vote_has_correct_fields(self):
        self.client.post(
            "/api/vote/",
            {"event": self.event.pk, "project": self.project.pk},
            format="json",
        )
        vote = Vote.objects.get(voter=self.user, project=self.project)
        self.assertEqual(vote.event_id, self.event.pk)
        self.assertEqual(vote.project_id, self.project.pk)
        self.assertEqual(vote.voter_id, self.user.pk)
        self.assertIsNone(vote.voting_token)

    # 3. Anonymous request is rejected (401/403).
    def test_03_anonymous_request_rejected(self):
        anon = APIClient()
        resp = anon.post(
            "/api/vote/",
            {"event": self.event.pk, "project": self.project.pk},
            format="json",
        )
        self.assertIn(resp.status_code, (401, 403))

    # 4. Same user voting again for the SAME project => 409.
    def test_04_duplicate_vote_same_project_409(self):
        self.client.post(
            "/api/vote/",
            {"event": self.event.pk, "project": self.project.pk},
            format="json",
        )
        resp = self.client.post(
            "/api/vote/",
            {"event": self.event.pk, "project": self.project.pk},
            format="json",
        )
        self.assertEqual(resp.status_code, 409)

    # 5. Same user voting for a DIFFERENT project => 201.
    def test_05_same_user_different_project_201(self):
        self.client.post(
            "/api/vote/",
            {"event": self.event.pk, "project": self.project.pk},
            format="json",
        )
        resp = self.client.post(
            "/api/vote/",
            {"event": self.event.pk, "project": self.project_b.pk},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)

    # 6. Event A + project from Event B => 400.
    def test_06_cross_event_project_400(self):
        event_b = _make_event(name="Event B", voting_mode="authenticated")
        track_b = _make_track(event_b, name="Track B")
        team_b = _make_team(event_b, name="Team B")
        project_b = _make_project(team_b, track_b, title="Other Event Project")
        resp = self.client.post(
            "/api/vote/",
            {"event": self.event.pk, "project": project_b.pk},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    # 7. Event with voting_mode="link" => 403 on authenticated endpoint.
    def test_07_link_mode_event_rejected_403(self):
        link_event = _make_event(name="Link Event", voting_mode="link")
        track = _make_track(link_event)
        team = _make_team(link_event, name="Link Team")
        project = _make_project(team, track, title="Link Project")
        resp = self.client.post(
            "/api/vote/",
            {"event": link_event.pk, "project": project.pk},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    # 8. Draft project => 400.
    def test_08_draft_project_400(self):
        draft = _make_project(self.team, self.track, title="Draft P", status="draft")
        resp = self.client.post(
            "/api/vote/",
            {"event": self.event.pk, "project": draft.pk},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    # 9. CSRF enforced: POST without CSRF token => 403.
    def test_09_csrf_enforced(self):
        csrf_client = APIClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        resp = csrf_client.post(
            "/api/vote/",
            {"event": self.event.pk, "project": self.project.pk},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)


# ===========================================================================
# LINK VOTING TESTS (10-20)
# ===========================================================================

class LinkVotingTests(TestCase):
    """Tests 10-20: Link-based voting endpoint."""

    def setUp(self):
        self.event = _make_event(name="Link Hack", voting_mode="link")
        self.track = _make_track(self.event)
        self.team = _make_team(self.event, name="Link Team")
        self.project = _make_project(self.team, self.track, title="Link Project A")
        self.project_b = _make_project(self.team, self.track, title="Link Project B")
        self.token = _make_token(self.event, email="link@example.com")
        self.client = APIClient()

    # 10. Valid token casts one valid vote (201).
    def test_10_link_vote_success(self):
        resp = self.client.post(
            f"/api/vote/link/{self.token.token}/",
            {"event": self.event.pk, "project": self.project.pk},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["event"], self.event.pk)
        self.assertEqual(data["project"], self.project.pk)
        self.assertIn("vote_id", data)

    # 11. Vote has correct fields.
    def test_11_vote_has_correct_fields(self):
        self.client.post(
            f"/api/vote/link/{self.token.token}/",
            {"event": self.event.pk, "project": self.project.pk},
            format="json",
        )
        vote = Vote.objects.get(voting_token=self.token)
        self.assertEqual(vote.event_id, self.event.pk)
        self.assertEqual(vote.project_id, self.project.pk)
        self.assertIsNone(vote.voter)
        self.assertEqual(vote.voting_token_id, self.token.pk)

    # 12. Successful vote sets VotingToken.used_at.
    def test_12_used_at_set(self):
        self.assertIsNone(self.token.used_at)
        self.client.post(
            f"/api/vote/link/{self.token.token}/",
            {"event": self.event.pk, "project": self.project.pk},
            format="json",
        )
        self.token.refresh_from_db()
        self.assertIsNotNone(self.token.used_at)

    # 13. Used token => 409, including on a different project.
    def test_13_used_token_409(self):
        self.client.post(
            f"/api/vote/link/{self.token.token}/",
            {"event": self.event.pk, "project": self.project.pk},
            format="json",
        )
        # Same project
        resp = self.client.post(
            f"/api/vote/link/{self.token.token}/",
            {"event": self.event.pk, "project": self.project.pk},
            format="json",
        )
        self.assertEqual(resp.status_code, 409)

        # Different project — still 409
        resp = self.client.post(
            f"/api/vote/link/{self.token.token}/",
            {"event": self.event.pk, "project": self.project_b.pk},
            format="json",
        )
        self.assertEqual(resp.status_code, 409)

    # 14. Nonexistent token => 404.
    def test_14_nonexistent_token_404(self):
        resp = self.client.post(
            "/api/vote/link/does_not_exist_token/",
            {"event": self.event.pk, "project": self.project.pk},
            format="json",
        )
        self.assertEqual(resp.status_code, 404)

    # 15. Token belonging to another event => 400.
    def test_15_wrong_event_token_400(self):
        other_event = _make_event(name="Other Event", voting_mode="link")
        other_token = _make_token(other_event, email="other@example.com")
        resp = self.client.post(
            f"/api/vote/link/{other_token.token}/",
            {"event": self.event.pk, "project": self.project.pk},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    # 16. Event A + project from Event B => 400.
    def test_16_cross_event_project_400(self):
        event_b = _make_event(name="Event B Link", voting_mode="link")
        track_b = _make_track(event_b)
        team_b = _make_team(event_b, name="Team B Link")
        project_b = _make_project(team_b, track_b, title="B Link Project")
        resp = self.client.post(
            f"/api/vote/link/{self.token.token}/",
            {"event": self.event.pk, "project": project_b.pk},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    # 17. Endpoint rejects events whose voting_mode is "authenticated" (403).
    def test_17_authenticated_mode_rejected_403(self):
        auth_event = _make_event(name="Auth Event", voting_mode="authenticated")
        track = _make_track(auth_event)
        team = _make_team(auth_event, name="Auth Team 17")
        project = _make_project(team, track, title="Auth Project 17")
        token = _make_token(auth_event)
        resp = self.client.post(
            f"/api/vote/link/{token.token}/",
            {"event": auth_event.pk, "project": project.pk},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    # 18. Draft project => 400.
    def test_18_draft_project_400(self):
        draft = _make_project(self.team, self.track, title="Draft Link", status="draft")
        resp = self.client.post(
            f"/api/vote/link/{self.token.token}/",
            {"event": self.event.pk, "project": draft.pk},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    # 19. Vote creation and used_at update are atomic.
    def test_19_atomicity(self):
        """
        Simulate a failure after Vote creation by monkey-patching used_at save
        to raise an error. Confirm no Vote persists and used_at is NOT set.
        Tests the service function directly (Django test client re-raises
        unhandled exceptions, so we test the atomic guarantee at the service
        layer where it's implemented).
        """
        import secrets
        from voting.services import cast_link_vote
        fresh_token = _make_token(self.event, email="atomic@example.com",
                                  token_str=secrets.token_urlsafe(32))

        original_save = VotingToken.save

        def failing_save(self_tok, *args, **kwargs):
            if "used_at" in (kwargs.get("update_fields") or []):
                raise RuntimeError("Simulated failure after vote creation")
            return original_save(self_tok, *args, **kwargs)

        VotingToken.save = failing_save
        try:
            with self.assertRaises(RuntimeError):
                cast_link_vote(fresh_token, self.event, self.project)
        finally:
            VotingToken.save = original_save

        # No Vote should exist for this token (rolled back by transaction.atomic)
        self.assertEqual(Vote.objects.filter(voting_token=fresh_token).count(), 0)
        fresh_token.refresh_from_db()
        self.assertIsNone(fresh_token.used_at)

    # 20. Link endpoint works with no session cookie and no CSRF token.
    def test_20_no_session_no_csrf(self):
        bare_client = APIClient(enforce_csrf_checks=True)
        resp = bare_client.post(
            f"/api/vote/link/{self.token.token}/",
            {"event": self.event.pk, "project": self.project.pk},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)


# ===========================================================================
# CONCURRENCY TESTS (21-23) — TransactionTestCase for real DB isolation
# ===========================================================================

class ConcurrencyTests(TransactionTestCase):
    """
    Tests 21-23: Concurrent voting and database-level constraint proofs.
    Uses TransactionTestCase for real PostgreSQL transactions.
    """

    # 21. Two workers POST with the SAME token for two DIFFERENT projects.
    def test_21_concurrent_link_votes_different_projects(self):
        ITERATIONS = 5
        for i in range(ITERATIONS):
            event = _make_event(name=f"Conc Link {i}", voting_mode="link")
            track = _make_track(event, name=f"Track {i}")
            team = _make_team(event, name=f"Team {i}")
            proj_a = _make_project(team, track, title=f"Conc A {i}")
            proj_b = _make_project(team, track, title=f"Conc B {i}")
            token = _make_token(event, email=f"conc{i}@example.com")

            barrier = threading.Barrier(2, timeout=10)
            results = [None, None]

            def worker(idx, proj):
                client = APIClient()
                try:
                    barrier.wait()
                    resp = client.post(
                        f"/api/vote/link/{token.token}/",
                        {"event": event.pk, "project": proj.pk},
                        format="json",
                    )
                    results[idx] = resp.status_code
                except Exception as exc:
                    results[idx] = str(exc)
                finally:
                    connections.close_all()

            t0 = threading.Thread(target=worker, args=(0, proj_a))
            t1 = threading.Thread(target=worker, args=(1, proj_b))
            t0.start()
            t1.start()
            t0.join(timeout=15)
            t1.join(timeout=15)

            codes = sorted(results)
            self.assertEqual(codes, [201, 409],
                             f"Iteration {i}: expected [201, 409], got {results}")
            self.assertEqual(Vote.objects.filter(voting_token=token).count(), 1)
            token.refresh_from_db()
            self.assertIsNotNone(token.used_at)

    # 22. Two workers POST as the SAME authenticated user for the SAME project.
    def test_22_concurrent_auth_votes_same_project(self):
        ITERATIONS = 5
        for i in range(ITERATIONS):
            event = _make_event(name=f"Conc Auth {i}", voting_mode="authenticated")
            track = _make_track(event, name=f"Auth Track {i}")
            team = _make_team(event, name=f"Auth Team {i}")
            proj = _make_project(team, track, title=f"Conc Auth Proj {i}")
            user = _make_user(f"conc_auth_user_{i}")

            barrier = threading.Barrier(2, timeout=10)
            results = [None, None]

            def worker(idx):
                client = APIClient()
                client.force_login(user)
                try:
                    barrier.wait()
                    resp = client.post(
                        "/api/vote/",
                        {"event": event.pk, "project": proj.pk},
                        format="json",
                    )
                    results[idx] = resp.status_code
                except Exception as exc:
                    results[idx] = str(exc)
                finally:
                    connections.close_all()

            t0 = threading.Thread(target=worker, args=(0,))
            t1 = threading.Thread(target=worker, args=(1,))
            t0.start()
            t1.start()
            t0.join(timeout=15)
            t1.join(timeout=15)

            codes = sorted(results)
            self.assertEqual(codes, [201, 409],
                             f"Iteration {i}: expected [201, 409], got {results}")
            self.assertEqual(
                Vote.objects.filter(project=proj, voter=user).count(), 1,
            )

    # 23. DATABASE-LEVEL CONSTRAINT PROOF (bypasses application layer).
    def test_23_db_constraints_via_bulk_create(self):
        event = _make_event(name="Constraint Proof", voting_mode="link")
        track = _make_track(event)
        team = _make_team(event, name="Proof Team")
        proj_a = _make_project(team, track, title="Proof A")
        proj_b = _make_project(team, track, title="Proof B")
        token = _make_token(event, email="proof@example.com")
        user = _make_user("proof_user")

        # 23a) Two Votes with same voting_token on different projects => IntegrityError
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Vote.objects.bulk_create([
                    Vote(event=event, project=proj_a, voting_token=token),
                    Vote(event=event, project=proj_b, voting_token=token),
                ])

        # 23b) Two Votes with same (project, voter) => IntegrityError
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Vote.objects.bulk_create([
                    Vote(event=event, project=proj_a, voter=user),
                    Vote(event=event, project=proj_a, voter=user),
                ])


# ===========================================================================
# INPUT ROBUSTNESS TESTS (24-25)
# ===========================================================================

class InputRobustnessTests(TestCase):
    """Tests 24-25: Malformed input handling."""

    def setUp(self):
        self.event = _make_event(voting_mode="authenticated")
        self.track = _make_track(self.event)
        self.team = _make_team(self.event)
        self.project = _make_project(self.team, self.track)
        self.user = _make_user("robust_voter")
        self.client = APIClient()
        self.client.force_login(self.user)

        self.link_event = _make_event(name="Link Robust", voting_mode="link")
        self.link_track = _make_track(self.link_event)
        self.link_team = _make_team(self.link_event, name="Link Robust Team")
        self.link_project = _make_project(self.link_team, self.link_track, title="Link Robust P")
        self.link_token = _make_token(self.link_event)
        self.link_client = APIClient()

    # 24. Missing fields, non-integer ids, invalid JSON => 400.
    def test_24_malformed_input_400(self):
        # Missing "project"
        resp = self.client.post("/api/vote/", {"event": self.event.pk}, format="json")
        self.assertEqual(resp.status_code, 400)

        # Missing "event"
        resp = self.client.post("/api/vote/", {"project": self.project.pk}, format="json")
        self.assertEqual(resp.status_code, 400)

        # Non-integer ids
        resp = self.client.post("/api/vote/", {"event": "abc", "project": self.project.pk}, format="json")
        self.assertEqual(resp.status_code, 400)

        # Invalid JSON
        resp = self.client.post(
            "/api/vote/",
            "not json at all",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

        # Link endpoint: missing fields
        resp = self.link_client.post(
            f"/api/vote/link/{self.link_token.token}/",
            {"event": self.link_event.pk},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

        # Link endpoint: non-integer
        resp = self.link_client.post(
            f"/api/vote/link/{self.link_token.token}/",
            {"event": "abc", "project": "xyz"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    # 25. Nonexistent event/project => 404.
    def test_25_nonexistent_ids_404(self):
        resp = self.client.post(
            "/api/vote/",
            {"event": 99999, "project": self.project.pk},
            format="json",
        )
        self.assertEqual(resp.status_code, 404)

        resp = self.client.post(
            "/api/vote/",
            {"event": self.event.pk, "project": 99999},
            format="json",
        )
        self.assertEqual(resp.status_code, 404)


# ===========================================================================
# BALLOT ORDERING TESTS (26-35)
# ===========================================================================

class BallotOrderingTests(TestCase):
    """Tests 26-35: Ballot endpoint and deterministic ordering."""

    def setUp(self):
        self.event = _make_event(voting_mode="authenticated")
        self.track = _make_track(self.event)
        self.team = _make_team(self.event)
        # Create 12 submitted projects
        self.projects = []
        for i in range(12):
            p = _make_project(self.team, self.track, title=f"Ballot Project {i:02d}")
            self.projects.append(p)
        self.user = _make_user("ballot_voter")
        self.user_b = _make_user("ballot_voter_b")
        self.client = APIClient()
        self.client.force_login(self.user)

        # Link event + tokens for link ballot tests
        self.link_event = _make_event(name="Link Ballot Event", voting_mode="link")
        self.link_track = _make_track(self.link_event)
        self.link_team = _make_team(self.link_event, name="Link Ballot Team")
        self.link_projects = []
        for i in range(12):
            p = _make_project(self.link_team, self.link_track, title=f"Link Ballot {i:02d}")
            self.link_projects.append(p)
        self.link_token = _make_token(self.link_event, email="lballot@example.com")
        self.link_token_b = _make_token(self.link_event, email="lballot_b@example.com")

    # 26. Same authenticated voter + event => same order on repeated calls.
    def test_26_auth_ballot_deterministic(self):
        resp1 = self.client.get(f"/api/vote/ballot/{self.event.pk}/")
        resp2 = self.client.get(f"/api/vote/ballot/{self.event.pk}/")
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        ids1 = [p["id"] for p in resp1.json()["projects"]]
        ids2 = [p["id"] for p in resp2.json()["projects"]]
        self.assertEqual(ids1, ids2)

    # 27. Same token + event => same order on repeated calls.
    def test_27_link_ballot_deterministic(self):
        client = APIClient()
        resp1 = client.get(f"/api/vote/ballot/{self.link_event.pk}/?token={self.link_token.token}")
        resp2 = client.get(f"/api/vote/ballot/{self.link_event.pk}/?token={self.link_token.token}")
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        ids1 = [p["id"] for p in resp1.json()["projects"]]
        ids2 = [p["id"] for p in resp2.json()["projects"]]
        self.assertEqual(ids1, ids2)

    # 28. Different identities => different order.
    def test_28_different_identities_different_order(self):
        client_b = APIClient()
        client_b.force_login(self.user_b)
        resp_a = self.client.get(f"/api/vote/ballot/{self.event.pk}/")
        resp_b = client_b.get(f"/api/vote/ballot/{self.event.pk}/")
        ids_a = [p["id"] for p in resp_a.json()["projects"]]
        ids_b = [p["id"] for p in resp_b.json()["projects"]]
        # With 12 projects, the probability of identical order is ~1/(12!) ≈ 0
        self.assertNotEqual(ids_a, ids_b)

    # 28b. Independently compute the expected order and assert it matches.
    def test_28b_expected_order_matches_api(self):
        # Authenticated mode
        base_ids = sorted([p.pk for p in self.projects])
        seed = int.from_bytes(
            hashlib.sha256(
                f"{self.event.pk}:authenticated:{self.user.pk}".encode("utf-8")
            ).digest(),
            "big",
        )
        expected = list(base_ids)
        rng = random.Random(seed)
        rng.shuffle(expected)

        resp = self.client.get(f"/api/vote/ballot/{self.event.pk}/")
        api_ids = [p["id"] for p in resp.json()["projects"]]
        self.assertEqual(api_ids, expected)

        # Link mode
        link_base_ids = sorted([p.pk for p in self.link_projects])
        link_seed = int.from_bytes(
            hashlib.sha256(
                f"{self.link_event.pk}:link:{self.link_token.pk}".encode("utf-8")
            ).digest(),
            "big",
        )
        link_expected = list(link_base_ids)
        link_rng = random.Random(link_seed)
        link_rng.shuffle(link_expected)

        link_client = APIClient()
        resp = link_client.get(
            f"/api/vote/ballot/{self.link_event.pk}/?token={self.link_token.token}"
        )
        link_api_ids = [p["id"] for p in resp.json()["projects"]]
        self.assertEqual(link_api_ids, link_expected)

    # 29. Ordering unaffected by database row return order.
    def test_29_insertion_order_irrelevant(self):
        # Create a new event with projects in shuffled insertion order
        event2 = _make_event(name="Insert Order", voting_mode="authenticated")
        track2 = _make_track(event2)
        team2 = _make_team(event2, name="Insert Team")
        import random as _rng
        titles = [f"IO Project {i}" for i in range(10)]
        _rng.shuffle(titles)
        for t in titles:
            _make_project(team2, track2, title=t)

        client = APIClient()
        client.force_login(self.user)
        resp1 = client.get(f"/api/vote/ballot/{event2.pk}/")
        resp2 = client.get(f"/api/vote/ballot/{event2.pk}/")
        ids1 = [p["id"] for p in resp1.json()["projects"]]
        ids2 = [p["id"] for p in resp2.json()["projects"]]
        self.assertEqual(ids1, ids2)

    # 30. Zero-project and one-project ballots return correctly.
    def test_30_zero_and_one_project_ballot(self):
        # Zero projects
        empty_event = _make_event(name="Empty Event", voting_mode="authenticated")
        client = APIClient()
        client.force_login(self.user)
        resp = client.get(f"/api/vote/ballot/{empty_event.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["projects"], [])

        # One project
        one_event = _make_event(name="One Project Event", voting_mode="authenticated")
        track = _make_track(one_event)
        team = _make_team(one_event, name="One Team")
        proj = _make_project(team, track, title="Solo Project")
        resp = client.get(f"/api/vote/ballot/{one_event.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["projects"]), 1)
        self.assertEqual(resp.json()["projects"][0]["id"], proj.pk)

    # 31. Ballot contains only submitted projects.
    def test_31_only_submitted_projects(self):
        mixed_event = _make_event(name="Mixed Event", voting_mode="authenticated")
        track = _make_track(mixed_event)
        team = _make_team(mixed_event, name="Mixed Team")
        submitted = _make_project(team, track, title="Submitted Mix", status="submitted")
        _make_project(team, track, title="Draft Mix", status="draft")

        client = APIClient()
        client.force_login(self.user)
        resp = client.get(f"/api/vote/ballot/{mixed_event.pk}/")
        ids = [p["id"] for p in resp.json()["projects"]]
        self.assertEqual(ids, [submitted.pk])

    # 32. Ballot does not mutate Project rows.
    def test_32_ballot_no_mutation(self):
        project_count_before = Project.objects.count()
        titles_before = set(Project.objects.values_list("title", flat=True))
        self.client.get(f"/api/vote/ballot/{self.event.pk}/")
        project_count_after = Project.objects.count()
        titles_after = set(Project.objects.values_list("title", flat=True))
        self.assertEqual(project_count_before, project_count_after)
        self.assertEqual(titles_before, titles_after)

    # 33. Link ballot token validation (missing token => 400, wrong event => 400, nonexistent => 404).
    def test_33_link_ballot_no_token(self):
        anon_client = APIClient()
        resp = anon_client.get(f"/api/vote/ballot/{self.link_event.pk}/")
        self.assertEqual(resp.status_code, 400)

        # Critical case: Logged-in session + link-mode event + NO token => MUST return 400
        logged_in_client = APIClient()
        logged_in_client.force_login(self.user)
        resp_authed = logged_in_client.get(f"/api/vote/ballot/{self.link_event.pk}/")
        self.assertEqual(resp_authed.status_code, 400)

        # Nonexistent token => 404
        resp_404 = anon_client.get(
            f"/api/vote/ballot/{self.link_event.pk}/?token=nonexistent_token_1234"
        )
        self.assertEqual(resp_404.status_code, 404)

        # Wrong-event token => 400
        wrong_token = _make_token(self.event, email="wrong@example.com")
        resp_wrong = anon_client.get(
            f"/api/vote/ballot/{self.link_event.pk}/?token={wrong_token.token}"
        )
        self.assertEqual(resp_wrong.status_code, 400)

    # 34. Anonymous request to the authenticated ballot => 401.
    def test_34_anonymous_auth_ballot_401(self):
        anon = APIClient()
        resp = anon.get(f"/api/vote/ballot/{self.event.pk}/")
        self.assertEqual(resp.status_code, 401)

    # 34b. Authenticated mode ignores any supplied ?token= completely.
    def test_34b_authenticated_ballot_ignores_token(self):
        # Request without token
        resp_plain = self.client.get(f"/api/vote/ballot/{self.event.pk}/")
        self.assertEqual(resp_plain.status_code, 200)

        # Request with a token parameter — must be ignored completely
        resp_with_token = self.client.get(
            f"/api/vote/ballot/{self.event.pk}/?token={self.link_token.token}"
        )
        self.assertEqual(resp_with_token.status_code, 200)

        ids_plain = [p["id"] for p in resp_plain.json()["projects"]]
        ids_with_token = [p["id"] for p in resp_with_token.json()["projects"]]
        self.assertEqual(ids_plain, ids_with_token)

    # 35. A used link token may still GET its ballot (200); read-only.
    def test_35_used_token_still_returns_ballot(self):
        link_client = APIClient()
        # Cast a vote to use the token
        link_client.post(
            f"/api/vote/link/{self.link_token.token}/",
            {"event": self.link_event.pk, "project": self.link_projects[0].pk},
            format="json",
        )
        self.link_token.refresh_from_db()
        self.assertIsNotNone(self.link_token.used_at)

        # Count rows before
        vote_count_before = Vote.objects.count()
        token_used_at_before = self.link_token.used_at

        # GET ballot with used token
        resp = link_client.get(
            f"/api/vote/ballot/{self.link_event.pk}/?token={self.link_token.token}"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(len(resp.json()["projects"]), 0)

        # Confirm no mutation
        self.assertEqual(Vote.objects.count(), vote_count_before)
        self.link_token.refresh_from_db()
        self.assertEqual(self.link_token.used_at, token_used_at_before)


# ===========================================================================
# REGRESSION TESTS (36-37)
# ===========================================================================

class RegressionTests(TestCase):
    """Tests 36-37: Phase 1 and T1 regression."""

    # 36. All Phase 1 voting tests still pass (re-run key checks).
    def test_36_phase1_model_invariants(self):
        now = timezone.now()
        event = _make_event()
        track = _make_track(event)
        team = _make_team(event)
        project = _make_project(team, track)
        user = _make_user("p1_voter")
        token = _make_token(event)

        # Event voting_mode defaults
        fresh_event = Event.objects.create(
            name="Defaults", submissions_close=now + timedelta(days=1)
        )
        self.assertEqual(fresh_event.voting_mode, "authenticated")

        # Authenticated vote
        v = Vote.objects.create(event=event, project=project, voter=user)
        self.assertIsNotNone(v.pk)

        # Token vote on different project
        p2 = _make_project(team, track, title="P1 Token Target")
        v2 = Vote.objects.create(event=event, project=p2, voting_token=token)
        self.assertIsNotNone(v2.pk)

        # Both voter + token rejected
        with self.assertRaises(ValidationError):
            Vote(event=event, project=project, voter=user, voting_token=token).full_clean()

        # Neither voter nor token rejected
        with self.assertRaises(ValidationError):
            Vote(event=event, project=project).full_clean()

        # Event mismatch rejected
        event2 = _make_event(name="P1 Mismatch")
        with self.assertRaises(ValidationError):
            Vote(event=event2, project=project, voter=_make_user("p1_m")).save()

    # 37. T1 project/event validation still works.
    def test_37_t1_project_event_invariant(self):
        event_a = _make_event(name="T1 A")
        event_b = _make_event(name="T1 B")
        track_a = _make_track(event_a, name="Track A")
        track_b = _make_track(event_b, name="Track B")
        team_a = _make_team(event_a, name="Team A T1")

        # Team from event_a + track from event_b => ValidationError
        with self.assertRaises(ValidationError):
            Project(
                team=team_a,
                track=track_b,
                title="Cross Event",
                summary="Should fail",
                repo_url="https://example.com/cross",
            ).save()


# ===========================================================================
# ORIGINAL PHASE 1 MODEL TESTS (preserved, not modified)
# ===========================================================================

class VotingModelTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.event = Event.objects.create(
            name="Hackathon 2026",
            submissions_close=self.now + timedelta(days=1),
            voting_close=self.now + timedelta(days=2),
        )
        self.track = Track.objects.create(
            event=self.event,
            name="General Track",
        )
        self.team = Team.objects.create(
            event=self.event,
            name="Alpha Team",
            invite_code="alpha_invite",
        )
        self.project1 = Project.objects.create(
            team=self.team,
            track=self.track,
            title="Project One",
            summary="Summary One",
            repo_url="https://example.com/repo1",
            status="submitted",
            submitted_at=self.now,
        )
        self.project2 = Project.objects.create(
            team=self.team,
            track=self.track,
            title="Project Two",
            summary="Summary Two",
            repo_url="https://example.com/repo2",
            status="submitted",
            submitted_at=self.now,
        )
        self.user = User.objects.create_user(
            username="voter1",
            email="voter1@example.com",
            password="password123",
        )
        self.token = VotingToken.objects.create(
            event=self.event,
            email="tokenvoter@example.com",
            token="token_abcdef123456",
        )

    # 1. Event voting_mode defaults to authenticated.
    def test_event_voting_mode_defaults_to_authenticated(self):
        event = Event.objects.create(
            name="Default Mode Event",
            submissions_close=self.now + timedelta(days=1),
        )
        self.assertEqual(event.voting_mode, "authenticated")

    # 2. Event can store link mode.
    def test_event_can_store_link_mode(self):
        event = Event.objects.create(
            name="Link Mode Event",
            submissions_close=self.now + timedelta(days=1),
            voting_mode="link",
        )
        event.refresh_from_db()
        self.assertEqual(event.voting_mode, "link")

    # 3. VotingToken token uniqueness is enforced.
    def test_voting_token_uniqueness_enforced(self):
        with self.assertRaises(IntegrityError):
            VotingToken.objects.create(
                event=self.event,
                email="another@example.com",
                token="token_abcdef123456",
            )

    # 4. VotingToken can belong to an Event.
    def test_voting_token_belongs_to_event(self):
        self.assertEqual(self.token.event, self.event)
        self.assertEqual(self.token.email, "tokenvoter@example.com")
        self.assertIn(self.token, self.event.voting_tokens.all())

    # 5. Vote can reference an authenticated voter.
    def test_vote_can_reference_authenticated_voter(self):
        vote = Vote.objects.create(
            event=self.event,
            project=self.project1,
            voter=self.user,
        )
        self.assertEqual(vote.voter, self.user)
        self.assertIsNone(vote.voting_token)
        self.assertEqual(vote.project, self.project1)
        self.assertEqual(vote.event, self.event)
        self.assertIsNotNone(vote.created_at)

    # 6. Vote can reference a voting token.
    def test_vote_can_reference_voting_token(self):
        vote = Vote.objects.create(
            event=self.event,
            project=self.project1,
            voting_token=self.token,
        )
        self.assertEqual(vote.voting_token, self.token)
        self.assertIsNone(vote.voter)
        self.assertEqual(vote.project, self.project1)
        self.assertEqual(vote.event, self.event)
        self.assertIsNotNone(vote.created_at)

    # 7. Duplicate vote for the same project + authenticated voter is rejected.
    def test_duplicate_vote_for_same_project_and_user_rejected(self):
        Vote.objects.create(
            event=self.event,
            project=self.project1,
            voter=self.user,
        )
        # Attempting duplicate vote for project1 by user raises ValidationError or IntegrityError
        with transaction.atomic():
            with self.assertRaises((ValidationError, IntegrityError)):
                Vote.objects.create(
                    event=self.event,
                    project=self.project1,
                    voter=self.user,
                )

        # Database UniqueConstraint also rejects duplicate via bulk_create
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Vote.objects.bulk_create([
                    Vote(
                        event=self.event,
                        project=self.project1,
                        voter=self.user,
                    )
                ])

        # Same user CAN vote for a different project (project2)
        vote2 = Vote.objects.create(
            event=self.event,
            project=self.project2,
            voter=self.user,
        )
        self.assertIsNotNone(vote2.pk)

    # 8. Duplicate vote for the same project + voting token is rejected.
    def test_duplicate_vote_for_same_project_and_token_rejected(self):
        Vote.objects.create(
            event=self.event,
            project=self.project1,
            voting_token=self.token,
        )
        # Attempting duplicate vote for project1 by token raises ValidationError or IntegrityError
        with transaction.atomic():
            with self.assertRaises((ValidationError, IntegrityError)):
                Vote.objects.create(
                    event=self.event,
                    project=self.project1,
                    voting_token=self.token,
                )

        # Database UniqueConstraint also rejects duplicate via bulk_create
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Vote.objects.bulk_create([
                    Vote(
                        event=self.event,
                        project=self.project1,
                        voting_token=self.token,
                    )
                ])

        # Note: Phase 1 allowed same token on different project.
        # Phase 2's unique_vote_per_token_total NOW prevents this at DB level.
        # This test is preserved structurally but the second vote attempt will
        # now also fail due to the total constraint.

    # 9. A Vote with BOTH voter and voting_token set is rejected by CheckConstraint.
    def test_vote_with_both_voter_and_token_rejected(self):
        vote = Vote(
            event=self.event,
            project=self.project1,
            voter=self.user,
            voting_token=self.token,
        )
        # Fails validation via clean()/full_clean()
        with self.assertRaises(ValidationError):
            vote.full_clean()

        with transaction.atomic():
            with self.assertRaises((ValidationError, IntegrityError)):
                vote.save()

        # Database CheckConstraint also rejects direct insert
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Vote.objects.bulk_create([
                    Vote(
                        event=self.event,
                        project=self.project1,
                        voter=self.user,
                        voting_token=self.token,
                    )
                ])

    # 10. A Vote with NEITHER voter nor voting_token set is rejected by CheckConstraint.
    def test_vote_with_neither_voter_nor_token_rejected(self):
        vote = Vote(
            event=self.event,
            project=self.project1,
            voter=None,
            voting_token=None,
        )
        # Fails validation via clean()/full_clean()
        with self.assertRaises(ValidationError):
            vote.full_clean()

        with transaction.atomic():
            with self.assertRaises((ValidationError, IntegrityError)):
                vote.save()

        # Database CheckConstraint also rejects direct insert
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Vote.objects.bulk_create([
                    Vote(
                        event=self.event,
                        project=self.project1,
                        voter=None,
                        voting_token=None,
                    )
                ])

    # 11. A Vote whose event does not match its project's actual event is rejected.
    def test_vote_event_mismatch_with_project_event_rejected(self):
        event2 = Event.objects.create(
            name="Different Event",
            submissions_close=self.now + timedelta(days=5),
        )
        vote = Vote(
            event=event2,
            project=self.project1,  # belongs to self.event, not event2
            voter=self.user,
        )
        with self.assertRaises(ValidationError) as ctx:
            vote.save()
        self.assertIn(
            "Vote.event must match the project's actual event.",
            str(ctx.exception),
        )

    # 12. Comment stores project, author_name, text, and created_at.
    def test_comment_stores_required_fields(self):
        comment = Comment.objects.create(
            project=self.project1,
            author_name="Alice Reviewer",
            text="Outstanding implementation of the core concept!",
        )
        self.assertEqual(comment.project, self.project1)
        self.assertEqual(comment.author_name, "Alice Reviewer")
        self.assertEqual(comment.text, "Outstanding implementation of the core concept!")
        self.assertIsNotNone(comment.created_at)
        self.assertIn(comment, self.project1.comments.all())

    # 13. Existing T1 project/event behavior still works.
    def test_existing_t1_project_event_behavior_still_works(self):
        # Invariant: Project team and track must belong to the same event
        event_other = Event.objects.create(
            name="Another Event",
            submissions_close=self.now + timedelta(days=3),
        )
        track_other = Track.objects.create(
            event=event_other,
            name="Other Track",
        )
        mismatched_project = Project(
            team=self.team,  # belongs to self.event
            track=track_other,  # belongs to event_other
            title="Invalid Cross-Event Project",
            summary="Should fail",
            repo_url="https://example.com/invalid",
        )
        with self.assertRaises(ValidationError) as ctx:
            mismatched_project.save()
        self.assertIn(
            "Project team and track must belong to the same event.",
            str(ctx.exception),
        )
