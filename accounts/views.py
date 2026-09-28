"""
Authentication views for the DOGFOOD 2026 hackathon platform.

Provides:
- login_view: standard Django session login
- logout_view: standard Django session logout
- whoami: minimal placeholder endpoint that returns the current user's
  username and role as JSON (used to verify checker sessions work)
"""
import json

from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods


@require_http_methods(["GET", "POST"])
def login_view(request):
    """Standard Django session login view."""
    if request.method == "GET":
        return render(request, "accounts/login.html")

    username = request.POST.get("username", "")
    password = request.POST.get("password", "")
    user = authenticate(request, username=username, password=password)

    if user is not None:
        login(request, user)
        return redirect("whoami")

    return render(request, "accounts/login.html", {"error": "Invalid credentials."})


@require_http_methods(["GET", "POST"])
def logout_view(request):
    """Standard Django session logout."""
    logout(request)
    return redirect("login")


@require_http_methods(["GET"])
def whoami(request):
    """
    Minimal authenticated placeholder endpoint.

    Returns JSON with the current user's authentication status, username,
    and role (from Profile). Used to verify that checker sessions resolve
    request.user correctly.
    """
    if not request.user.is_authenticated:
        return JsonResponse(
            {"authenticated": False, "username": None, "role": None},
            status=200,
        )

    role = None
    if hasattr(request.user, "profile"):
        role = request.user.profile.role

    return JsonResponse(
        {
            "authenticated": True,
            "username": request.user.username,
            "role": role,
        },
        status=200,
    )
