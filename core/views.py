"""
Dashboard views for the DOGFOOD 2026 platform.

Provides role-aware dashboard experiences for:
- Organizer / Admin (Full control-center with real metrics, judging progress, voting state, recent projects)
- Judge (Assigned projects workload, completed scoring, rubric criteria, strictly isolated from peer scores)
- Participant (Team status, project submission state, community voting links)
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.utils import timezone

from accounts.models import User
from events.models import Event
from judging.models import JudgeAssignment, RubricCriterion, Score
from projects.models import Project
from teams.models import Team, TeamMembership
from voting.models import Vote


@login_required(login_url="/accounts/login/")
def dashboard_view(request):
    """
    Primary authenticated landing page (/dashboard/).
    Determines user role and renders the appropriate role-aware dashboard.
    """
    profile = getattr(request.user, "profile", None)
    role = profile.role if profile else "participant"

    # Superuser or staff has organizer capabilities
    if request.user.is_superuser or request.user.is_staff:
        role = "organizer"

    active_event = Event.objects.first()
    now = timezone.now()

    if role in ("organizer", "admin"):
        # Real metrics query — zero fabricated data
        total_projects = Project.objects.count()
        submitted_projects = Project.objects.filter(status="submitted").count()
        draft_projects = Project.objects.filter(status="draft").count()
        total_teams = Team.objects.count()
        total_judges = User.objects.filter(profile__role="judge").count()

        # Real judging progress
        total_assignments = JudgeAssignment.objects.count()
        total_scores = Score.objects.count()
        outstanding_assignments = max(0, total_assignments - total_scores)
        judging_progress_pct = (
            int((total_scores / total_assignments) * 100)
            if total_assignments > 0
            else 0
        )

        # Real community voting state
        is_voting_open = (
            (active_event.voting_close is None or active_event.voting_close > now)
            if active_event
            else False
        )
        total_votes = Vote.objects.count()
        results_visible = not is_voting_open

        # Real recent projects
        recent_projects = (
            Project.objects.select_related("team", "track")
            .order_by("-submitted_at", "-id")[:6]
        )

        context = {
            "active_event": active_event,
            "total_projects": total_projects,
            "submitted_projects": submitted_projects,
            "draft_projects": draft_projects,
            "total_teams": total_teams,
            "total_judges": total_judges,
            "total_assignments": total_assignments,
            "total_scores": total_scores,
            "outstanding_assignments": outstanding_assignments,
            "judging_progress_pct": judging_progress_pct,
            "is_voting_open": is_voting_open,
            "total_votes": total_votes,
            "results_visible": results_visible,
            "recent_projects": recent_projects,
            "role": role,
        }
        return render(request, "dashboard/organizer.html", context)

    elif role == "judge":
        # Judge dashboard: strict backend isolation — judge sees ONLY own assignments & scores
        assignments = (
            JudgeAssignment.objects.filter(judge=request.user)
            .select_related("project", "project__team", "project__track")
            .order_by("project__id")
        )
        assigned_count = assignments.count()

        # Query judge's own scores only (never peer scores)
        judge_scores = {
            s.project_id: s
            for s in Score.objects.filter(judge=request.user)
        }
        completed_count = len(judge_scores)
        remaining_count = max(0, assigned_count - completed_count)
        progress_pct = (
            int((completed_count / assigned_count) * 100)
            if assigned_count > 0
            else 0
        )

        # Rubric criteria for the event
        criteria = (
            RubricCriterion.objects.filter(event=active_event)
            if active_event
            else []
        )

        enriched_assignments = []
        for a in assignments:
            s = judge_scores.get(a.project_id)
            enriched_assignments.append({
                "assignment": a,
                "project": a.project,
                "is_scored": bool(s),
                "criteria_scores": s.criteria_scores if s else {},
                "comment": s.comment if s else "",
            })

        context = {
            "active_event": active_event,
            "enriched_assignments": enriched_assignments,
            "assigned_count": assigned_count,
            "completed_count": completed_count,
            "remaining_count": remaining_count,
            "progress_pct": progress_pct,
            "criteria": criteria,
            "role": role,
        }
        return render(request, "dashboard/judge.html", context)

    else:
        # Participant workspace: real team & project data
        membership = (
            TeamMembership.objects.filter(user=request.user)
            .select_related("team", "team__event")
            .first()
        )
        team = membership.team if membership else None
        teammates = (
            TeamMembership.objects.filter(team=team).select_related("user")
            if team
            else []
        )
        project = (
            Project.objects.filter(team=team).select_related("track").first()
            if team
            else None
        )

        is_submission_open = (
            (active_event.submissions_close is None or active_event.submissions_close > now)
            if active_event
            else False
        )
        is_voting_open = (
            (active_event.voting_close is None or active_event.voting_close > now)
            if active_event
            else False
        )

        context = {
            "active_event": active_event,
            "team": team,
            "teammates": teammates,
            "project": project,
            "membership": membership,
            "is_submission_open": is_submission_open,
            "is_voting_open": is_voting_open,
            "role": role,
        }
        return render(request, "dashboard/participant.html", context)
