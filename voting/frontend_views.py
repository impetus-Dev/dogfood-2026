"""
Frontend HTML views for voting: ballot and results pages.
"""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from projects.models import Project
from voting.models import Vote, VotingToken
from voting.services import (
    DuplicateVoteError,
    TokenAlreadyUsedError,
    VotingClosedError,
    cast_authenticated_vote,
    cast_link_vote,
    get_results,
    is_voting_closed,
    ordered_ballot,
)


def ballot_view(request, event_id):
    """
    Public / user-facing ballot page for an event.
    Supports both authenticated voting and link-based voting (?token=...).
    Maintains deterministic seeded ballot ordering from the backend.
    """
    event = get_object_or_404(Event, pk=event_id)
    voting_closed = is_voting_closed(event)

    token_str = request.GET.get("token") or request.POST.get("token", "").strip()
    token_obj = None
    token_error = None
    token_used = False

    projects = []
    voted_project_ids = []
    has_voted = False

    if event.voting_mode == "link":
        if not token_str:
            token_error = "A voting token is required to view the ballot for this event."
        else:
            try:
                token_obj = VotingToken.objects.get(token=token_str)
                if token_obj.event_id != event.pk:
                    token_error = "This voting token belongs to a different event."
                    token_obj = None
                else:
                    token_used = token_obj.used_at is not None
                    projects = ordered_ballot(event, "link", token_obj.pk)
                    if token_used:
                        voted_project_ids = list(
                            Vote.objects.filter(voting_token=token_obj).values_list("project_id", flat=True)
                        )
                        has_voted = True
            except VotingToken.DoesNotExist:
                token_error = "Voting token not found or invalid."

    elif event.voting_mode == "authenticated":
        if request.user.is_authenticated:
            projects = ordered_ballot(event, "authenticated", request.user.pk)
            voted_project_ids = list(
                Vote.objects.filter(event=event, voter=request.user).values_list("project_id", flat=True)
            )
            has_voted = len(voted_project_ids) > 0
        else:
            # Anonymous user in authenticated event: show empty or unranked projects, prompt login
            projects = list(
                Project.objects.filter(team__event=event, status="submitted").select_related("track").order_by("pk")
            )

    # Handle standard POST form submission fallback
    if request.method == "POST":
        project_id = request.POST.get("project")
        if not project_id:
            messages.error(request, "Please select a project to vote for.")
        else:
            try:
                project = Project.objects.get(pk=project_id, team__event=event, status="submitted")
            except Project.DoesNotExist:
                messages.error(request, "Selected project not found in this event.")
                project = None

            if project:
                if event.voting_mode == "authenticated":
                    if not request.user.is_authenticated:
                        messages.error(request, "You must be logged in to cast a vote.")
                    else:
                        try:
                            cast_authenticated_vote(request.user, event, project)
                            messages.success(request, f"Your vote for '{project.title}' has been successfully recorded!")
                            voted_project_ids.append(project.pk)
                            has_voted = True
                        except DuplicateVoteError:
                            messages.error(request, "You have already voted for this project.")
                        except VotingClosedError:
                            messages.error(request, "Voting is closed for this event.")
                        except Exception as e:
                            messages.error(request, str(e))

                elif event.voting_mode == "link":
                    if not token_obj:
                        messages.error(request, "A valid voting token is required.")
                    else:
                        try:
                            cast_link_vote(token_obj, event, project)
                            messages.success(request, f"Your vote for '{project.title}' has been successfully recorded!")
                            voted_project_ids.append(project.pk)
                            has_voted = True
                            token_used = True
                        except TokenAlreadyUsedError:
                            messages.error(request, "This voting token has already been used.")
                        except VotingClosedError:
                            messages.error(request, "Voting is closed for this event.")
                        except Exception as e:
                            messages.error(request, str(e))

    return render(
        request,
        "voting/ballot.html",
        {
            "event": event,
            "voting_closed": voting_closed,
            "projects": projects,
            "token_str": token_str,
            "token_obj": token_obj,
            "token_error": token_error,
            "token_used": token_used,
            "voted_project_ids": voted_project_ids,
            "has_voted": has_voted,
        },
    )


def link_ballot_view(request, token):
    """
    Direct link-based voting access: /vote/link/<token>/
    Finds the event associated with the token and renders the ballot.
    """
    token_obj = get_object_or_404(VotingToken, token=token)
    return redirect(f"{reverse('ballot_page', kwargs={'event_id': token_obj.event_id})}?token={token}")


def results_view(request, event_id):
    """
    Public results page for an event.
    Results are strictly hidden until voting is closed.
    """
    event = get_object_or_404(Event, pk=event_id)
    voting_closed = is_voting_closed(event)

    results = []
    total_votes = 0

    if voting_closed:
        results = get_results(event)
        total_votes = sum(item["votes"] for item in results)

    return render(
        request,
        "voting/results.html",
        {
            "event": event,
            "voting_closed": voting_closed,
            "results": results,
            "total_votes": total_votes,
        },
    )
