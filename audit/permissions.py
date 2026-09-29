"""
Permissions for the audit app.
"""
from rest_framework.permissions import BasePermission


class IsOrganizer(BasePermission):
    """
    Allow access strictly to authenticated users with 'organizer' or 'admin' role.
    Denies access to participant, judge, visitor, and anonymous users.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        profile = getattr(request.user, "profile", None)
        if profile and profile.role in ("organizer", "admin"):
            return True

        if request.user.is_staff or request.user.is_superuser:
            return True

        return False
