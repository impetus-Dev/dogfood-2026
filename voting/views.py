"""
Voting API views.

Each view explicitly sets authentication_classes and permission_classes
rather than relying on the global REST_FRAMEWORK defaults.
"""
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from events.models import Event
from projects.models import Project
from voting.models import Vote, VotingToken
from voting.serializers import VoteInputSerializer
from voting.throttles import (
    AuthenticatedUserThrottle,
    AuthUserThrottle,
    LinkIpThrottle,
    LinkIPThrottle,
    LinkTokenThrottle,
)
from voting.services import (
    DuplicateVoteError,
    TokenAlreadyUsedError,
    VotingClosedError,
    cast_authenticated_vote,
    cast_link_vote,
    get_results,
    is_voting_closed,
    ordered_ballot,
    tally_results,
)


class AuthenticatedVoteView(APIView):
    """
    POST /api/vote/
    Authenticated mode: user identity comes from the session cookie.
    CSRF remains enforced (DRF SessionAuthentication default).
    """
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [AuthenticatedUserThrottle]


    def post(self, request):
        serializer = VoteInputSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        event_id = serializer.validated_data["event"]
        project_id = serializer.validated_data["project"]

        # Look up event
        try:
            event = Event.objects.get(pk=event_id)
        except Event.DoesNotExist:
            return Response(
                {"detail": "Event not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Event must be in authenticated mode
        if event.voting_mode != "authenticated":
            return Response(
                {"detail": "This event does not use authenticated voting."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Look up project
        try:
            project = Project.objects.select_related("team", "track").get(pk=project_id)
        except Project.DoesNotExist:
            return Response(
                {"detail": "Project not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Project must belong to the requested event
        if project.team.event_id != event.pk:
            return Response(
                {"detail": "Project does not belong to this event."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Project must be submitted
        if project.status != "submitted":
            return Response(
                {"detail": "Only submitted projects can be voted on."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Cast the vote
        try:
            vote = cast_authenticated_vote(request.user, event, project)
        except VotingClosedError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_403_FORBIDDEN,
            )
        except DuplicateVoteError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_409_CONFLICT,
            )
        except (ValidationError, IntegrityError):
            # ValidationError from full_clean() or IntegrityError from race
            if Vote.objects.filter(project=project, voter=request.user).exists():
                return Response(
                    {"detail": "You have already voted for this project."},
                    status=status.HTTP_409_CONFLICT,
                )
            return Response(
                {"detail": "Vote could not be created."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "event": event.pk,
                "project": project.pk,
                "vote_id": vote.pk,
            },
            status=status.HTTP_201_CREATED,
        )


class LinkVoteView(APIView):
    """
    POST /api/vote/link/<token>/
    Link-based mode: the token in the URL is the sole credential.
    No session authentication, no CSRF.
    """
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LinkTokenThrottle, LinkIpThrottle]

    def post(self, request, token):
        serializer = VoteInputSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        event_id = serializer.validated_data["event"]
        project_id = serializer.validated_data["project"]

        # Look up token
        try:
            token_obj = VotingToken.objects.get(token=token)
        except VotingToken.DoesNotExist:
            return Response(
                {"detail": "Token not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Look up event
        try:
            event = Event.objects.get(pk=event_id)
        except Event.DoesNotExist:
            return Response(
                {"detail": "Event not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Event must be in link mode
        if event.voting_mode != "link":
            return Response(
                {"detail": "This event does not use link-based voting."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Look up project
        try:
            project = Project.objects.select_related("team", "track").get(pk=project_id)
        except Project.DoesNotExist:
            return Response(
                {"detail": "Project not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Token must belong to the requested event
        if token_obj.event_id != event.pk:
            return Response(
                {"detail": "Token does not belong to this event."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Project must belong to the requested event
        if project.team.event_id != event.pk:
            return Response(
                {"detail": "Project does not belong to this event."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Project must be submitted
        if project.status != "submitted":
            return Response(
                {"detail": "Only submitted projects can be voted on."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Cast the vote — try/except OUTSIDE atomic() per Step 3A
        try:
            vote = cast_link_vote(token_obj, event, project)
        except VotingClosedError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_403_FORBIDDEN,
            )
        except TokenAlreadyUsedError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_409_CONFLICT,
            )
        except (ValidationError, IntegrityError):
            # Race condition: check what failed
            if Vote.objects.filter(voting_token=token_obj).exists() or VotingToken.objects.filter(pk=token_obj.pk, used_at__isnull=False).exists():
                return Response(
                    {"detail": "This voting token has already been used."},
                    status=status.HTTP_409_CONFLICT,
                )
            return Response(
                {"detail": "Vote could not be created."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "event": event.pk,
                "project": project.pk,
                "vote_id": vote.pk,
            },
            status=status.HTTP_201_CREATED,
        )


class BallotView(APIView):
    """
    GET /api/vote/ballot/<event_id>/

    Authenticated mode: requires session authentication.
    Link mode: requires ?token=<token> query parameter.

    Returns submitted projects in deterministic, identity-seeded order.
    Read-only: never creates or modifies any Vote or VotingToken.
    """
    # SessionAuthentication populates request.user from session cookies.
    # AllowAny allows unauthenticated requests through (for link-mode ballots).
    # The view manually checks auth for authenticated-mode requests.
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def get(self, request, event_id):
        # Look up event
        try:
            event = Event.objects.get(pk=event_id)
        except Event.DoesNotExist:
            return Response(
                {"detail": "Event not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if event.voting_mode == "authenticated":
            if not request.user or not request.user.is_authenticated:
                return Response(
                    {"detail": "Authentication credentials were not provided."},
                    status=status.HTTP_401_UNAUTHORIZED,
                )
            # If ?token= is supplied in authenticated mode, IGNORE it completely.
            # Identity is strictly request.user.pk
            projects = ordered_ballot(event, "authenticated", request.user.pk)

        elif event.voting_mode == "link":
            # In link mode, ?token= is REQUIRED regardless of session or login state.
            # A logged-in session MUST NOT substitute for the token.
            token_str = request.query_params.get("token")
            if not token_str:
                return Response(
                    {"detail": "Voting token is required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                token_obj = VotingToken.objects.get(token=token_str)
            except VotingToken.DoesNotExist:
                return Response(
                    {"detail": "Token not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if token_obj.event_id != event.pk:
                return Response(
                    {"detail": "Token does not belong to this event."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # A used token may still fetch the ballot (read-only 200)
            projects = ordered_ballot(event, "link", token_obj.pk)

        else:
            return Response(
                {"detail": "Invalid voting mode."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Build response
        project_data = [
            {
                "id": p.pk,
                "title": p.title,
                "summary": p.summary,
                "track": p.track.name,
            }
            for p in projects
        ]

        return Response(
            {
                "event": event.pk,
                "projects": project_data,
            },
            status=status.HTTP_200_OK,
        )


class ResultsView(APIView):
    """
    GET /api/results/<event_id>/

    Public, read-only. Returns vote counts per submitted project.
    Results are hidden until voting closes.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, event_id):
        # Look up event
        try:
            event = Event.objects.get(pk=event_id)
        except Event.DoesNotExist:
            return Response(
                {"detail": "Event not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Delegate business logic to get_results in voting.services
        try:
            projects = get_results(event)
        except VotingClosedError:
            return Response(
                {"detail": "Results are hidden until voting closes."},
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response(
            {
                "event": event.pk,
                "projects": projects,
            },
            status=status.HTTP_200_OK,
        )
