from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models

from events.models import Event
from projects.models import Project


class VotingToken(models.Model):
    """
    Token used for link-based anonymous voting.
    """
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="voting_tokens",
    )
    email = models.EmailField()
    token = models.CharField(max_length=64, unique=True)
    used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.email} ({self.token})"


class Vote(models.Model):
    """
    Represents a cast vote for a project in an event.
    Supports either an authenticated user or a link-based voting token.
    Enforces exact-one-identity and event-consistency invariants.
    """
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="votes",
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="votes",
    )
    voter = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="votes",
    )
    voting_token = models.ForeignKey(
        VotingToken,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="votes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # Invariant 1: Duplicate vote for the same project + authenticated voter is rejected
            models.UniqueConstraint(
                fields=["project", "voter"],
                condition=models.Q(voter__isnull=False),
                name="unique_vote_per_user",
            ),
            # Invariant 2: Duplicate vote for the same project + voting token is rejected
            models.UniqueConstraint(
                fields=["project", "voting_token"],
                condition=models.Q(voting_token__isnull=False),
                name="unique_vote_per_token",
            ),
            # Invariant A: Exactly one of {voter, voting_token} must be set (never both, never neither)
            models.CheckConstraint(
                check=(
                    (models.Q(voter__isnull=False) & models.Q(voting_token__isnull=True))
                    | (models.Q(voter__isnull=True) & models.Q(voting_token__isnull=False))
                ),
                name="vote_exactly_one_identity",
            ),
            # Invariant: One token can cast at most one vote total (across all projects)
            models.UniqueConstraint(
                fields=["voting_token"],
                condition=models.Q(voting_token__isnull=False),
                name="unique_vote_per_token_total",
            ),
        ]

    def clean(self):
        super().clean()
        # Invariant B: Vote.event must always match the actual event of Vote.project
        if self.project_id and self.event_id:
            if self.project.team.event_id != self.event_id:
                raise ValidationError(
                    "Vote.event must match the project's actual event."
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Vote for {self.project.title} in {self.event.name}"


class Comment(models.Model):
    """
    Public comment on a project.
    """
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    author_name = models.CharField(max_length=255)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Comment by {self.author_name} on {self.project.title}"
