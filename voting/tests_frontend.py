import secrets
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event, Track
from projects.models import Project
from teams.models import Team, TeamMembership
from voting.models import Comment, Vote, VotingToken

User = get_user_model()


class VotingFrontendTests(TestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()

        # Users
        self.voter1 = User.objects.create_user(username="voter_alice", password="password123")
        self.voter2 = User.objects.create_user(username="voter_bob", password="password123")

        # Events
        self.auth_event = Event.objects.create(
            name="Alpha Hackathon 2026",
            submissions_close=timezone.now() + timezone.timedelta(days=1),
            voting_mode="authenticated",
            voting_close=timezone.now() + timezone.timedelta(days=2),
        )
        self.link_event = Event.objects.create(
            name="Beta Community 2026",
            submissions_close=timezone.now() + timezone.timedelta(days=1),
            voting_mode="link",
            voting_close=timezone.now() + timezone.timedelta(days=2),
        )

        # Tracks & Teams
        self.track1 = Track.objects.create(event=self.auth_event, name="Web3 Track")
        self.team1 = Team.objects.create(event=self.auth_event, name="Team 1", invite_code="code1")
        TeamMembership.objects.create(team=self.team1, user=self.voter1)

        self.project1 = Project.objects.create(
            team=self.team1,
            track=self.track1,
            title="Solaris Protocol",
            summary="Next-gen clean solar grid.",
            repo_url="https://github.com/example/solaris",
            status="submitted",
        )
        self.project2 = Project.objects.create(
            team=self.team1,
            track=self.track1,
            title="Quantum Relay",
            summary="Decentralized quantum communication network.",
            repo_url="https://github.com/example/quantum",
            status="submitted",
        )

        # Link event projects
        self.track2 = Track.objects.create(event=self.link_event, name="AI Track")
        self.team2 = Team.objects.create(event=self.link_event, name="Team 2", invite_code="code2")
        self.link_project = Project.objects.create(
            team=self.team2,
            track=self.track2,
            title="Neural Synth",
            summary="Creative AI music composition engine.",
            repo_url="https://github.com/example/neural",
            status="submitted",
        )

    def test_ballot_page_authenticated_user_sees_seeded_order(self):
        self.client.force_login(self.voter1)
        resp = self.client.get(reverse("ballot_page", kwargs={"event_id": self.auth_event.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Alpha Hackathon 2026")
        self.assertContains(resp, "Solaris Protocol")
        self.assertContains(resp, "Quantum Relay")
        self.assertContains(resp, "voter_alice")
        self.assertContains(resp, "Vote for Project")

    def test_ballot_page_anonymous_prompts_login(self):
        resp = self.client.get(reverse("ballot_page", kwargs={"event_id": self.auth_event.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "You must be logged in to cast an authenticated vote.")
        self.assertContains(resp, "Log In")

    def test_ballot_page_link_flow_with_valid_token(self):
        token_str = secrets.token_urlsafe(32)
        VotingToken.objects.create(event=self.link_event, token=token_str)

        # Direct link view redirects with token param
        resp_redirect = self.client.get(reverse("link_ballot_page", kwargs={"token": token_str}))
        self.assertEqual(resp_redirect.status_code, 302)

        # Target ballot page renders projects with active voting token
        resp = self.client.get(f"{reverse('ballot_page', kwargs={'event_id': self.link_event.pk})}?token={token_str}")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Neural Synth")
        self.assertContains(resp, "Active voting link verified")
        self.assertContains(resp, "Vote for Project")

    def test_ballot_page_link_flow_missing_or_invalid_token(self):
        # Missing token on link event
        resp_missing = self.client.get(reverse("ballot_page", kwargs={"event_id": self.link_event.pk}))
        self.assertEqual(resp_missing.status_code, 200)
        self.assertContains(resp_missing, "A voting token is required to view the ballot for this event.")

        # Invalid token
        resp_invalid = self.client.get(f"{reverse('ballot_page', kwargs={'event_id': self.link_event.pk})}?token=non_existent_token")
        self.assertEqual(resp_invalid.status_code, 200)
        self.assertContains(resp_invalid, "Voting token not found or invalid.")

    def test_ballot_form_post_authenticated_vote_and_duplicate_blocked(self):
        self.client.force_login(self.voter1)
        url = reverse("ballot_page", kwargs={"event_id": self.auth_event.pk})

        # Cast first vote
        resp1 = self.client.post(url, {"project": self.project1.pk})
        self.assertEqual(resp1.status_code, 200)
        self.assertTrue(Vote.objects.filter(event=self.auth_event, voter=self.voter1, project=self.project1).exists())
        self.assertContains(resp1, "Your vote for &#x27;Solaris Protocol&#x27; has been successfully recorded!")

        # Cast duplicate vote
        resp2 = self.client.post(url, {"project": self.project1.pk})
        self.assertEqual(resp2.status_code, 200)
        self.assertContains(resp2, "You have already voted for this project.")

    def test_ballot_form_post_link_vote_and_reuse_blocked(self):
        token_str = secrets.token_urlsafe(32)
        vt = VotingToken.objects.create(event=self.link_event, token=token_str)
        url = reverse("ballot_page", kwargs={"event_id": self.link_event.pk})

        # Cast vote with link token
        resp1 = self.client.post(url, {"project": self.link_project.pk, "token": token_str})
        self.assertEqual(resp1.status_code, 200)
        vt.refresh_from_db()
        self.assertIsNotNone(vt.used_at)
        self.assertTrue(Vote.objects.filter(event=self.link_event, voting_token=vt, project=self.link_project).exists())

        # Attempt reuse
        resp2 = self.client.post(url, {"project": self.link_project.pk, "token": token_str})
        self.assertEqual(resp2.status_code, 200)
        self.assertContains(resp2, "This voting token has already been used.")

    def test_results_page_strictly_hidden_pre_close(self):
        # Event is open, results must be hidden
        url = reverse("results_page", kwargs={"event_id": self.auth_event.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Results are Hidden")
        self.assertContains(resp, "Results are hidden until voting closes")
        # Ensure no table, rank, or project tally is leaked in HTML
        self.assertNotContains(resp, "results-table")
        self.assertNotContains(resp, "Total Votes Cast")

    def test_results_page_shows_real_tallies_post_close(self):
        # Cast votes
        Vote.objects.create(event=self.auth_event, project=self.project1, voter=self.voter1)
        Vote.objects.create(event=self.auth_event, project=self.project1, voter=self.voter2)

        # Close the event
        self.auth_event.voting_close = timezone.now() - timezone.timedelta(hours=1)
        self.auth_event.save()

        url = reverse("results_page", kwargs={"event_id": self.auth_event.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Community Voting Leaderboard")
        self.assertContains(resp, "Total Votes Cast: 2")
        self.assertContains(resp, "Solaris Protocol")
        self.assertContains(resp, "results-table")

    def test_project_detail_shows_comments_and_submits_comment(self):
        # Initial comment
        Comment.objects.create(project=self.project1, author_name="Reviewer Dave", text="Impressive prototype!")

        url = reverse("projects:detail", kwargs={"pk": self.project1.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Community Comments")
        self.assertContains(resp, "Reviewer Dave")
        self.assertContains(resp, "Impressive prototype!")
        self.assertContains(resp, "Leave a Comment")
        self.assertContains(resp, "btn-post-comment")

    def test_ballot_page_closed_voting_state(self):
        self.auth_event.voting_close = timezone.now() - timezone.timedelta(hours=1)
        self.auth_event.save()
        self.client.force_login(self.voter1)
        resp = self.client.get(reverse("ballot_page", kwargs={"event_id": self.auth_event.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Voting Closed")
        self.assertContains(resp, "voting-closed-alert")
        self.assertContains(resp, "Closed")

    def test_ballot_page_already_voted_state(self):
        Vote.objects.create(event=self.auth_event, project=self.project1, voter=self.voter1)
        self.client.force_login(self.voter1)
        resp = self.client.get(reverse("ballot_page", kwargs={"event_id": self.auth_event.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f"voted-btn-{self.project1.pk}")
        self.assertContains(resp, "Voted &check;")

    def test_results_page_ordering_preserved(self):
        Vote.objects.create(event=self.auth_event, project=self.project2, voter=self.voter1)
        Vote.objects.create(event=self.auth_event, project=self.project2, voter=self.voter2)
        voter3 = User.objects.create_user(username="voter_charlie", password="password123")
        Vote.objects.create(event=self.auth_event, project=self.project1, voter=voter3)

        self.auth_event.voting_close = timezone.now() - timezone.timedelta(hours=1)
        self.auth_event.save()

        resp = self.client.get(reverse("results_page", kwargs={"event_id": self.auth_event.pk}))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")
        pos_quantum = content.find("Quantum Relay")
        pos_solaris = content.find("Solaris Protocol")
        self.assertTrue(pos_quantum != -1 and pos_solaris != -1)
        self.assertTrue(pos_quantum < pos_solaris)

    def test_security_ballot_and_results_no_sensitive_data_leak(self):
        token_str = secrets.token_urlsafe(32)
        vt = VotingToken.objects.create(event=self.link_event, token=token_str)

        # 1. Ballot page
        resp_ballot = self.client.get(f"{reverse('ballot_page', kwargs={'event_id': self.link_event.pk})}?token={token_str}")
        self.assertEqual(resp_ballot.status_code, 200)
        ballot_content = resp_ballot.content.decode("utf-8")
        # Invite codes must never be leaked
        self.assertNotIn("code1", ballot_content)
        self.assertNotIn("code2", ballot_content)
        # Raw token must not appear in visible body text outside hidden form inputs
        body_without_inputs = ballot_content.replace(f'value="{token_str}"', '').replace(f'"{token_str}"', '')
        self.assertNotIn(token_str, body_without_inputs)

        # 2. Results page
        self.link_event.voting_close = timezone.now() - timezone.timedelta(hours=1)
        self.link_event.save()
        resp_results = self.client.get(reverse("results_page", kwargs={"event_id": self.link_event.pk}))
        self.assertEqual(resp_results.status_code, 200)
        results_content = resp_results.content.decode("utf-8")
        self.assertNotIn("code1", results_content)
        self.assertNotIn("code2", results_content)
        self.assertNotIn(token_str, results_content)
