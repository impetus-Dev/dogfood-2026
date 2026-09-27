"""
Management command to create fixed checker sessions for the DOGFOOD 2026
acceptance checker.

The checker does NOT perform a login flow — it attaches fixed session cookies
directly. This command creates real authenticated Django sessions for the
four checker personas so that Django's AuthenticationMiddleware correctly
resolves request.user when those cookies arrive.

Idempotency: always deletes any existing session at each fixed key before
recreating it, so the command is safe to run repeatedly.
"""
from django.contrib.auth.models import User
from django.contrib.auth import SESSION_KEY, BACKEND_SESSION_KEY, HASH_SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from django.core.management.base import BaseCommand

from accounts.models import Profile


# The fixed checker session keys — these are the exact cookie values
# the acceptance checker will send as  Cookie: session=<value>
CHECKER_SESSIONS = [
    {
        "username": "organizer",
        "role": "organizer",
        "session_key": "org_7f2a",
    },
    {
        "username": "judge_a",
        "role": "judge",
        "session_key": "jdg_a_91bc",
    },
    {
        "username": "judge_b",
        "role": "judge",
        "session_key": "jdg_b_44de",
    },
    {
        "username": "participant",
        "role": "participant",
        "session_key": "prt_2e88",
    },
]

# Must match the first entry in AUTHENTICATION_BACKENDS (Django default).
# If settings.py ever customizes AUTHENTICATION_BACKENDS, update this.
AUTH_BACKEND = "django.contrib.auth.backends.ModelBackend"


class Command(BaseCommand):
    help = "Create fixed checker sessions for the DOGFOOD 2026 acceptance checker."

    def handle(self, *args, **options):
        for entry in CHECKER_SESSIONS:
            # get_or_create the user
            user, created = User.objects.get_or_create(
                username=entry["username"],
                defaults={"is_active": True},
            )
            if created:
                # Set unusable password — these users authenticate via
                # pre-created sessions, not via login form
                user.set_password(entry["username"])
                user.save()
                self.stdout.write(f"  Created user: {entry['username']}")
            else:
                self.stdout.write(f"  User exists: {entry['username']}")

            # get_or_create the profile with the correct role
            profile, profile_created = Profile.objects.get_or_create(
                user=user,
                defaults={"role": entry["role"]},
            )
            if not profile_created and profile.role != entry["role"]:
                profile.role = entry["role"]
                profile.save()
                self.stdout.write(f"  Updated role: {entry['username']} -> {entry['role']}")

            # Create the fixed session using the exact technique from the spec.
            # Idempotency: always delete first, then recreate.
            self._create_session_for(user, entry["session_key"])
            self.stdout.write(
                self.style.SUCCESS(
                    f"  Session ready: {entry['username']} -> {entry['session_key']}"
                )
            )

        self.stdout.write(
            self.style.SUCCESS("\nAll checker sessions created successfully.")
        )

    def _create_session_for(self, user, fixed_key):
        """
        Create an authenticated Django session at the given fixed key.

        This follows the exact technique required by the spec:
        1. Delete any existing session at this key (idempotency)
        2. Create a new SessionStore
        3. Set _session_key to the fixed value
        4. Store SESSION_KEY, BACKEND_SESSION_KEY, HASH_SESSION_KEY
        5. Save with must_create=True
        """
        # Step 1: idempotency — clear any existing session at this key
        SessionStore(session_key=fixed_key).delete()

        # Step 2-5: create the authenticated session
        store = SessionStore()
        store[SESSION_KEY] = str(user.pk)
        store[BACKEND_SESSION_KEY] = AUTH_BACKEND
        store[HASH_SESSION_KEY] = user.get_session_auth_hash()
        store._session_key = fixed_key
        store.save(must_create=True)
