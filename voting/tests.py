from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from events.models import Event, Track
from projects.models import Project
from teams.models import Team
from voting.models import Comment, Vote, VotingToken


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

        # Same token CAN vote for a different project (project2)
        vote2 = Vote.objects.create(
            event=self.event,
            project=self.project2,
            voting_token=self.token,
        )
        self.assertIsNotNone(vote2.pk)

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
