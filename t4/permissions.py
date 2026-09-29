from rest_framework import permissions


class IsOrganizerOrAdmin(permissions.BasePermission):
    """
    Allows access only to authenticated users with organizer or admin profile role.
    Explicitly checks request.user.profile.role, not is_staff or is_superuser.
    """

    def has_permission(self, request, view):
        profile = getattr(request.user, "profile", None)
        return bool(profile and profile.role in ("organizer", "admin"))
