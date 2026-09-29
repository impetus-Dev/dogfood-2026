"""
Views for hackathon judging (T2).

Includes:
1. JudgeScoresView (GET /api/judge/scores/):
   - 401 if unauthenticated.
   - 403 if user.profile.role not in ['judge', 'organizer', 'admin'].
   - Support ?judge=<id_or_username>.
   - BACKEND ROLE ISOLATION: 403 if ?judge= requested and does not match request.user,
     unless requester is 'organizer' or 'admin'.
   - Return JSON with the judge's scored projects, criterion breakdown, and comments.

2. ExportCSVView (GET /api/export.csv):
   - 401 if unauthenticated.
   - 403 if user.profile.role not in ['organizer', 'admin'].
   - Return text/csv with Content-Disposition: attachment; filename="results.csv".
   - First line (header) contains a comma (',').
   - Export columns: project_id,project_title,track,submitted_at,review_count.
"""

from collections import defaultdict
import csv
from io import StringIO
from typing import Any, Dict, List

from django.contrib.auth import get_user_model
from django.http import HttpResponse, JsonResponse
from django.views import View

from judging.models import Score
from projects.models import Project


class JudgeScoresView(View):
    """
    GET /api/judge/scores/
    Returns scored projects, criterion breakdown, and comments for a judge.
    Enforces strict backend role isolation.
    """

    def get(self, request, *args, **kwargs):
        # 1. 401 if unauthenticated
        if not request.user.is_authenticated:
            return JsonResponse(
                {"error": "Unauthorized", "detail": "Authentication required."},
                status=401,
            )

        # 2. 403 if user.profile.role not in ['judge', 'organizer', 'admin']
        try:
            profile = getattr(request.user, "profile", None)
            role = getattr(profile, "role", None) if profile else None
        except Exception:
            role = None

        if role not in ["judge", "organizer", "admin"]:
            return JsonResponse(
                {"error": "Forbidden", "detail": "Access restricted to judges, organizers, and admins."},
                status=403,
            )

        # 3. Query parameter ?judge=<id_or_username>
        judge_param = request.GET.get("judge")
        target_user = None

        if judge_param is not None and str(judge_param).strip() != "":
            judge_param_str = str(judge_param).strip()
            user_id_str = str(getattr(request.user, "pk", getattr(request.user, "id", "")))
            username_str = str(getattr(request.user, "username", ""))

            matches_user = (
                judge_param_str == user_id_str
                or judge_param_str.lower() == username_str.lower()
            )

            # BACKEND ROLE ISOLATION:
            # If ?judge= does not match request.user, return HTTP 403 unless requester is 'organizer' or 'admin'
            if not matches_user and role not in ["organizer", "admin"]:
                return JsonResponse(
                    {
                        "error": "Forbidden",
                        "detail": "Judges are strictly prohibited from viewing other judges' scores.",
                    },
                    status=403,
                )

            if matches_user:
                target_user = request.user
            else:
                User = get_user_model()
                if judge_param_str.isdigit():
                    target_user = User.objects.filter(pk=int(judge_param_str)).first()
                if target_user is None:
                    target_user = User.objects.filter(username__iexact=judge_param_str).first()
                if target_user is None:
                    target_user = User.objects.filter(username=judge_param_str).first()

                if target_user is None:
                    return JsonResponse(
                        {"error": "Not Found", "detail": "Judge not found."},
                        status=404,
                    )
        else:
            # Default to authenticated user's own scores
            target_user = request.user

        # 4. Fetch judge's scored projects
        scores = (
            Score.objects.filter(judge=target_user)
            .select_related("project", "project__track")
            .order_by("-updated_at", "-id")
        )

        scored_projects: List[Dict[str, Any]] = []
        for s in scores:
            proj = s.project
            track_name = ""
            if proj and getattr(proj, "track", None):
                track_name = getattr(proj.track, "name", str(proj.track))

            item = {
                "project_id": proj.id if proj else None,
                "project_title": getattr(proj, "title", "") if proj else "",
                "track": track_name,
                "criteria_scores": s.criteria_scores if s.criteria_scores is not None else {},
                "comment": s.comment or "",
                "updated_at": s.updated_at.isoformat() if getattr(s, "updated_at", None) else None,
            }
            scored_projects.append(item)

        return JsonResponse(scored_projects, safe=False)


class ExportCSVView(View):
    """
    GET /api/export.csv
    Exports judging results as CSV for organizers and admins.
    """

    def get(self, request, *args, **kwargs):
        # 1. 401 if unauthenticated
        if not request.user.is_authenticated:
            return HttpResponse(
                "Unauthorized: Authentication required.",
                status=401,
                content_type="text/plain",
            )

        # 2. 403 if user.profile.role not in ['organizer', 'admin']
        try:
            profile = getattr(request.user, "profile", None)
            role = getattr(profile, "role", None) if profile else None
        except Exception:
            role = None

        if role not in ["organizer", "admin"]:
            return HttpResponse(
                "Forbidden: Access restricted to organizers and admins.",
                status=403,
                content_type="text/plain",
            )

        # 3. Query projects
        projects_qs = Project.objects.select_related("track").all()
        event_param = request.GET.get("event") or request.GET.get("event_id")
        if event_param:
            try:
                projects_qs = projects_qs.filter(track__event_id=event_param)
            except Exception:
                pass

        projects = list(projects_qs.order_by("id"))

        # 4. Count completed reviews per project across completed judge ballots
        completed_scores = Score.objects.filter(
            criteria_scores__isnull=False
        ).select_related("judge", "project")

        project_judges = defaultdict(set)
        for s in completed_scores:
            if s.criteria_scores != {}:
                project_judges[s.project_id].add(s.judge_id)

        # 5. Build CSV
        output = StringIO()
        writer = csv.writer(output, lineterminator="\r\n")

        # CRITICAL ACCEPTANCE REQUIREMENT: The first line (header) MUST contain a comma (',')
        writer.writerow(["project_id", "project_title", "track", "submitted_at", "review_count"])

        for proj in projects:
            track_name = ""
            if getattr(proj, "track", None):
                track_name = getattr(proj.track, "name", str(proj.track))

            sub_at = ""
            if getattr(proj, "submitted_at", None):
                if hasattr(proj.submitted_at, "isoformat"):
                    sub_at = proj.submitted_at.isoformat()
                else:
                    sub_at = str(proj.submitted_at)

            review_count = len(project_judges.get(proj.id, set()))
            writer.writerow([proj.id, getattr(proj, "title", ""), track_name, sub_at, review_count])

        response = HttpResponse(output.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="results.csv"'
        return response
