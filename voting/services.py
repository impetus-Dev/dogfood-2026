"""
Voting service layer.

All core voting logic lives here. Views parse/validate input, call these
functions, and map exceptions to HTTP status codes.
"""
import hashlib
import random

from django.db import IntegrityError, transaction
from django.utils import timezone

from voting.models import Vote, VotingToken


class DuplicateVoteError(Exception):
    """Raised when a vote would duplicate an existing vote."""
    pass


class TokenAlreadyUsedError(Exception):
    """Raised when a voting token has already been used."""
    pass


def cast_authenticated_vote(user, event, project):
    """
    Cast a vote as an authenticated user.

    Returns the created Vote instance.
    Raises DuplicateVoteError if the user already voted for this project.
    May raise ValidationError (from full_clean) or IntegrityError (race).
    """
    # Pre-check for a friendly error message
    if Vote.objects.filter(project=project, voter=user).exists():
        raise DuplicateVoteError(
            "You have already voted for this project."
        )

    vote = Vote(
        event=event,
        project=project,
        voter=user,
        voting_token=None,
    )
    vote.save()
    return vote


def cast_link_vote(token_obj, event, project):
    """
    Cast a vote using a link-based voting token.

    All lookups and validation happen OUTSIDE the transaction.
    The atomic block re-fetches the token with select_for_update() to
    serialise concurrent requests.

    Returns the created Vote instance.
    Raises TokenAlreadyUsedError if the token was already used.
    Raises DuplicateVoteError on constraint violation.
    """
    # Pre-check outside transaction for friendly error
    if token_obj.used_at is not None or Vote.objects.filter(voting_token=token_obj).exists():
        raise TokenAlreadyUsedError(
            "This voting token has already been used."
        )

    with transaction.atomic():
        # Re-fetch with row lock inside transaction
        locked_token = VotingToken.objects.select_for_update().get(pk=token_obj.pk)

        # Re-check under lock
        if locked_token.used_at is not None or Vote.objects.filter(voting_token=locked_token).exists():
            raise TokenAlreadyUsedError(
                "This voting token has already been used."
            )

        vote = Vote(
            event=event,
            project=project,
            voter=None,
            voting_token=locked_token,
        )
        vote.save()

        locked_token.used_at = timezone.now()
        locked_token.save(update_fields=["used_at"])

    return vote


def ordered_ballot(event, mode, identity_id):
    """
    Return the event's submitted projects in a deterministic, identity-seeded
    order.

    Args:
        event: Event instance
        mode: "authenticated" or "link" (literal string matching Event.voting_mode)
        identity_id: user.pk (authenticated) or VotingToken.pk (link) — never
                     the secret token string

    The algorithm:
    1. Base list = submitted projects ordered by pk (stable input order)
    2. Seed = SHA-256 of "{event.pk}:{mode}:{identity_id}" interpreted as big-endian int
    3. Shuffle with a LOCAL random.Random(seed); never touches the global RNG

    Note: adding new projects between two requests can change a voter's order;
    that is acceptable.
    """
    from projects.models import Project

    projects = list(
        Project.objects.filter(
            team__event=event,
            status="submitted",
        ).select_related("track").order_by("pk")
    )

    if len(projects) <= 1:
        return projects

    seed = int.from_bytes(
        hashlib.sha256(
            f"{event.pk}:{mode}:{identity_id}".encode("utf-8")
        ).digest(),
        "big",
    )

    rng = random.Random(seed)
    rng.shuffle(projects)

    return projects
