import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import (
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotAllowed,
    JsonResponse,
)
from django.middleware.csrf import CsrfViewMiddleware
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from events.models import Track
from teams.models import Team, TeamMembership
from .forms import ProjectForm, ProjectEditForm
from .models import Project


def _extract_request_data(request):
    """
    Safely extract request data from either JSON payload or POST form body.
    Never uses bracket indexing.
    """
    if request.content_type == "application/json":
        try:
            return json.loads(request.body.decode("utf-8") if isinstance(request.body, bytes) else request.body)
        except (ValueError, TypeError, json.JSONDecodeError):
            return None
    return request.POST


def _is_json_request(request):
    """Check if the client requested JSON response or sent JSON payload."""
    return (
        request.content_type == "application/json"
        or request.headers.get("Accept") == "application/json"
    )


def project_create(request):
    """
    Create a new project draft.
    Authenticated users only. Validates title, summary, repo_url, team, track, and same-event invariant.
    Any missing field returns a clean 400 Bad Request, never an unhandled exception or 500.
    """
    if not request.user.is_authenticated:
        if _is_json_request(request):
            return JsonResponse({"error": "Authentication required."}, status=401)
        return redirect(f"{reverse('login')}?next={request.path}")

    if request.method == "GET":
        user_teams = Team.objects.filter(memberships__user=request.user).select_related("event")
        tracks = Track.objects.select_related("event").all()
        form = ProjectForm(user=request.user)
        return render(
            request,
            "projects/create.html",
            {
                "form": form,
                "user_teams": user_teams,
                "tracks": tracks,
            },
        )

    if request.method == "POST":
        # Enforce CSRF on browser form submissions; exempt JSON/API payloads
        if request.content_type != "application/json":
            csrf_err = CsrfViewMiddleware(lambda r: None).process_view(request, None, (), {})
            if csrf_err:
                return csrf_err

        data = _extract_request_data(request)
        if data is None:
            return JsonResponse({"error": "Invalid JSON body."}, status=400)

        form = ProjectForm(data, user=request.user)
        if not form.is_valid():
            if _is_json_request(request):
                return JsonResponse({"errors": form.errors}, status=400)
            user_teams = Team.objects.filter(memberships__user=request.user).select_related("event")
            tracks = Track.objects.select_related("event").all()
            return render(
                request,
                "projects/create.html",
                {
                    "form": form,
                    "user_teams": user_teams,
                    "tracks": tracks,
                },
                status=400,
            )

        project = form.save(commit=False)
        project.status = "draft"
        project.submitted_at = None

        try:
            with transaction.atomic():
                project.save()
        except ValidationError as e:
            if _is_json_request(request):
                return JsonResponse({"error": str(e)}, status=400)
            form.add_error(None, e)
            user_teams = Team.objects.filter(memberships__user=request.user).select_related("event")
            tracks = Track.objects.select_related("event").all()
            return render(
                request,
                "projects/create.html",
                {
                    "form": form,
                    "user_teams": user_teams,
                    "tracks": tracks,
                },
                status=400,
            )

        if _is_json_request(request):
            return JsonResponse(
                {
                    "id": project.id,
                    "title": project.title,
                    "status": project.status,
                    "submitted_at": project.submitted_at,
                },
                status=201,
            )

        return redirect("projects:detail", pk=project.pk)

    return HttpResponseNotAllowed(["GET", "POST"])


project_create.csrf_exempt = True


def project_detail(request, pk):
    """
    Display project details, team info, track info, status, and edit/submit actions.
    """
    project = get_object_or_404(
        Project.objects.select_related("team", "track", "team__event"),
        pk=pk,
    )
    is_member = (
        TeamMembership.objects.filter(team=project.team, user=request.user).exists()
        if request.user.is_authenticated
        else False
    )
    is_deadline_passed = timezone.now() >= project.team.event.submissions_close

    return render(
        request,
        "projects/detail.html",
        {
            "project": project,
            "team": project.team,
            "track": project.track,
            "event": project.team.event,
            "is_member": is_member,
            "is_deadline_passed": is_deadline_passed,
            "can_edit": is_member and project.status == "draft",
            "can_submit": is_member and project.status == "draft" and not is_deadline_passed,
        },
    )


def project_edit(request, pk):
    """
    Edit a draft project. Only team members can edit, and only while status is draft.
    """
    if not request.user.is_authenticated:
        if _is_json_request(request):
            return JsonResponse({"error": "Authentication required."}, status=401)
        return redirect(f"{reverse('login')}?next={request.path}")

    project = get_object_or_404(
        Project.objects.select_related("team", "track", "team__event"),
        pk=pk,
    )

    if not TeamMembership.objects.filter(team=project.team, user=request.user).exists():
        if _is_json_request(request):
            return JsonResponse({"error": "You are not a member of this team."}, status=403)
        return HttpResponseForbidden("You are not a member of this project's team.")

    if project.status != "draft":
        if _is_json_request(request):
            return JsonResponse({"error": "Submitted projects cannot be edited."}, status=400)
        return HttpResponseBadRequest("Submitted projects cannot be edited.")

    if request.method == "GET":
        form = ProjectEditForm(instance=project)
        return render(
            request,
            "projects/edit.html",
            {
                "form": form,
                "project": project,
            },
        )

    if request.method == "POST":
        if request.content_type != "application/json":
            csrf_err = CsrfViewMiddleware(lambda r: None).process_view(request, None, (), {})
            if csrf_err:
                return csrf_err

        data = _extract_request_data(request)
        if data is None:
            return JsonResponse({"error": "Invalid JSON body."}, status=400)

        form = ProjectEditForm(data, instance=project)
        if not form.is_valid():
            if _is_json_request(request):
                return JsonResponse({"errors": form.errors}, status=400)
            return render(
                request,
                "projects/edit.html",
                {
                    "form": form,
                    "project": project,
                },
                status=400,
            )

        try:
            with transaction.atomic():
                project = form.save()
        except ValidationError as e:
            if _is_json_request(request):
                return JsonResponse({"error": str(e)}, status=400)
            form.add_error(None, e)
            return render(
                request,
                "projects/edit.html",
                {
                    "form": form,
                    "project": project,
                },
                status=400,
            )

        if _is_json_request(request):
            return JsonResponse(
                {
                    "id": project.id,
                    "title": project.title,
                    "summary": project.summary,
                    "repo_url": project.repo_url,
                    "status": project.status,
                }
            )

        return redirect("projects:detail", pk=project.pk)

    return HttpResponseNotAllowed(["GET", "POST"])


project_edit.csrf_exempt = True


def project_submit(request, pk):
    """
    Submit a draft project.
    Enforces team membership, draft status, and SERVER-SIDE SUBMISSION DEADLINE.
    Transition is executed atomically.
    """
    if not request.user.is_authenticated:
        if _is_json_request(request):
            return JsonResponse({"error": "Authentication required."}, status=401)
        return redirect(f"{reverse('login')}?next={request.path}")

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    if request.content_type != "application/json":
        csrf_err = CsrfViewMiddleware(lambda r: None).process_view(request, None, (), {})
        if csrf_err:
            return csrf_err

    project = get_object_or_404(
        Project.objects.select_related("team", "team__event"),
        pk=pk,
    )

    if not TeamMembership.objects.filter(team=project.team, user=request.user).exists():
        if _is_json_request(request):
            return JsonResponse({"error": "You are not a member of this team."}, status=403)
        return HttpResponseForbidden("You are not a member of this project's team.")

    if project.status != "draft":
        if _is_json_request(request):
            return JsonResponse({"error": "Project has already been submitted."}, status=400)
        return HttpResponseBadRequest("Project has already been submitted.")

    # Server-side deadline enforcement
    event = project.team.event
    if timezone.now() >= event.submissions_close:
        if _is_json_request(request):
            return JsonResponse({"error": "Submission deadline has passed."}, status=400)
        return HttpResponseBadRequest("Submission deadline has passed.")

    with transaction.atomic():
        project.status = "submitted"
        project.submitted_at = timezone.now()
        project.save(update_fields=["status", "submitted_at"])

    if _is_json_request(request):
        return JsonResponse(
            {
                "id": project.id,
                "title": project.title,
                "status": project.status,
                "submitted_at": project.submitted_at,
            }
        )

    return redirect("projects:detail", pk=project.pk)


project_submit.csrf_exempt = True
