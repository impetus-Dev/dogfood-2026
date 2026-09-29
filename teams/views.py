import secrets

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from events.models import Event
from .models import Team, TeamMembership


def generate_invite_code():
    """
    Generate a unique, unpredictable invite code with collision retries.
    Uses secrets.token_urlsafe(16), producing a 22-character URL-safe string
    well within the 64-character limit.
    """
    for _ in range(10):
        code = secrets.token_urlsafe(16)
        if not Team.objects.filter(invite_code=code).exists():
            return code
    raise RuntimeError("Failed to generate a unique invite code after 10 attempts.")


@login_required
def team_create(request):
    """
    Create a new team. Only authenticated users may create a team.
    Team creation and creator membership creation are wrapped in an atomic transaction.
    """
    if request.method == "GET":
        events = Event.objects.all().order_by("-submissions_close")
        return render(request, "teams/create.html", {"events": events})

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        event_id = request.POST.get("event_id")

        events = Event.objects.all().order_by("-submissions_close")
        if not name:
            return render(
                request,
                "teams/create.html",
                {"events": events, "error": "Team name is required."},
                status=400,
            )

        if not event_id:
            return render(
                request,
                "teams/create.html",
                {"events": events, "error": "Event selection is required."},
                status=400,
            )

        try:
            event = Event.objects.get(pk=event_id)
        except Event.DoesNotExist:
            return render(
                request,
                "teams/create.html",
                {"events": events, "error": "Selected event does not exist."},
                status=400,
            )

        with transaction.atomic():
            invite_code = generate_invite_code()
            team = Team.objects.create(
                event=event,
                name=name,
                invite_code=invite_code,
            )
            TeamMembership.objects.create(team=team, user=request.user)

        return redirect("teams:detail", pk=team.pk)

    return HttpResponseNotAllowed(["GET", "POST"])


def team_detail(request, pk):
    """
    Display team details, its event, member list, and the invite code / link.
    """
    team = get_object_or_404(Team.objects.select_related("event"), pk=pk)
    memberships = team.memberships.select_related("user").all()
    invite_url = request.build_absolute_uri(
        reverse("teams:join", args=[team.invite_code])
    )
    is_member = (
        memberships.filter(user=request.user).exists()
        if request.user.is_authenticated
        else False
    )

    return render(
        request,
        "teams/detail.html",
        {
            "team": team,
            "event": team.event,
            "memberships": memberships,
            "invite_url": invite_url,
            "is_member": is_member,
        },
    )


def join_team(request, invite_code):
    """
    GET/POST split join endpoint:
    - GET: strictly read-only, idempotent view. Looks up team by invite_code
      and renders confirmation page. Never mutates database state.
    - POST: mutating action. Requires authentication, creates membership using
      race-safe get_or_create, and redirects to team detail.
    """
    team = get_object_or_404(Team.objects.select_related("event"), invite_code=invite_code)

    if request.method == "GET":
        is_member = (
            team.memberships.filter(user=request.user).exists()
            if request.user.is_authenticated
            else False
        )
        return render(
            request,
            "teams/join_confirm.html",
            {
                "team": team,
                "event": team.event,
                "is_member": is_member,
            },
        )

    if request.method == "POST":
        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next={request.path}")

        # Atomic, race-safe membership creation
        TeamMembership.objects.get_or_create(team=team, user=request.user)
        return redirect("teams:detail", pk=team.pk)

    return HttpResponseNotAllowed(["GET", "POST"])
