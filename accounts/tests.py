"""
Comprehensive tests for Phase 1: Auth + Roles + Fixed Test Sessions.

Tests cover:
1. Profile model with five roles
2. Login succeeds with valid credentials
3. Login establishes a Django session
4. Logout invalidates authentication
5. SESSION_COOKIE_NAME is exactly "session"
6. create_checker_sessions creates the four users
7. Profiles receive the correct roles
8. Exact required session keys exist
9. create_checker_sessions is idempotent
10. org_7f2a resolves to organizer
11. jdg_a_91bc resolves to judge_a
12. jdg_b_44de resolves to judge_b
13. prt_2e88 resolves to participant
14. Invalid/unknown session does not authenticate a user

All session tests use Django's real session framework — cookies are
attached and middleware resolves them, ensuring HASH_SESSION_KEY and
backend-mismatch bugs are caught.
"""
import os
import importlib

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command

from .models import Profile


class ProfileModelTest(TestCase):
    """Tests for the Profile model and its roles."""

    def test_profile_has_five_roles(self):
        """Profile.ROLE_CHOICES contains exactly the five expected roles."""
        expected_roles = {"visitor", "participant", "judge", "organizer", "admin"}
        actual_roles = {choice[0] for choice in Profile.ROLE_CHOICES}
        self.assertEqual(actual_roles, expected_roles)

    def test_profile_creation(self):
        """A Profile can be created and linked to a User."""
        user = User.objects.create_user(username="testuser", password="password123")
        profile = Profile.objects.create(user=user, role="participant")
        self.assertEqual(profile.role, "participant")
        self.assertEqual(str(profile), "testuser (participant)")

    def test_profile_default_role(self):
        """Profile default role is 'participant'."""
        user = User.objects.create_user(username="testuser2", password="password123")
        profile = Profile.objects.create(user=user)
        self.assertEqual(profile.role, "participant")


class SessionCookieConfigTest(TestCase):
    """Tests for session cookie configuration."""

    def test_session_cookie_name(self):
        """SESSION_COOKIE_NAME is exactly 'session'."""
        self.assertEqual(settings.SESSION_COOKIE_NAME, "session")

    def test_session_cookie_secure_is_false(self):
        """SESSION_COOKIE_SECURE defaults to False for local dev."""
        # Django's default is False; we need it False for http://localhost
        self.assertFalse(settings.SESSION_COOKIE_SECURE)

    def test_secret_key_loaded(self):
        """SECRET_KEY is loaded and non-empty."""
        self.assertTrue(bool(settings.SECRET_KEY))

    def test_missing_secret_key_raises_improperly_configured(self):
        """If SECRET_KEY is missing from environment, ImproperlyConfigured is raised."""
        original_secret_key = os.environ.get("SECRET_KEY")
        try:
            if "SECRET_KEY" in os.environ:
                del os.environ["SECRET_KEY"]
            import config.settings
            with self.assertRaises(ImproperlyConfigured):
                importlib.reload(config.settings)
        finally:
            if original_secret_key is not None:
                os.environ["SECRET_KEY"] = original_secret_key
                import config.settings
                importlib.reload(config.settings)


class LoginLogoutTest(TestCase):
    """Tests for standard Django login/logout."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="logintest", password="testpass123"
        )
        Profile.objects.create(user=self.user, role="participant")

    def test_login_page_renders(self):
        """GET /accounts/login/ returns 200."""
        response = self.client.get("/accounts/login/")
        self.assertEqual(response.status_code, 200)

    def test_login_succeeds_with_valid_credentials(self):
        """POST with valid credentials redirects (login success)."""
        response = self.client.post(
            "/accounts/login/",
            {"username": "logintest", "password": "testpass123"},
        )
        self.assertEqual(response.status_code, 302)

    def test_login_establishes_session(self):
        """After login, the session cookie is set and whoami confirms auth."""
        self.client.login(username="logintest", password="testpass123")
        response = self.client.get("/accounts/whoami/")
        data = response.json()
        self.assertTrue(data["authenticated"])
        self.assertEqual(data["username"], "logintest")
        self.assertEqual(data["role"], "participant")

    def test_login_fails_with_invalid_credentials(self):
        """POST with invalid credentials returns login page with error."""
        response = self.client.post(
            "/accounts/login/",
            {"username": "logintest", "password": "wrongpass"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid credentials")

    def test_logout_invalidates_authentication(self):
        """After logout, whoami reports unauthenticated."""
        self.client.login(username="logintest", password="testpass123")
        # Confirm authenticated
        response = self.client.get("/accounts/whoami/")
        self.assertTrue(response.json()["authenticated"])
        # Logout
        self.client.get("/accounts/logout/")
        # Confirm no longer authenticated
        response = self.client.get("/accounts/whoami/")
        self.assertFalse(response.json()["authenticated"])


class CheckerSessionsCommandTest(TestCase):
    """Tests for the create_checker_sessions management command."""

    EXPECTED_SESSIONS = {
        "organizer": {"role": "organizer", "session_key": "org_7f2a"},
        "judge_a": {"role": "judge", "session_key": "jdg_a_91bc"},
        "judge_b": {"role": "judge", "session_key": "jdg_b_44de"},
        "participant": {"role": "participant", "session_key": "prt_2e88"},
    }

    def test_creates_four_users(self):
        """create_checker_sessions creates the four expected users."""
        call_command("create_checker_sessions")
        for username in self.EXPECTED_SESSIONS:
            self.assertTrue(
                User.objects.filter(username=username).exists(),
                f"User '{username}' was not created.",
            )

    def test_profiles_have_correct_roles(self):
        """Each checker user has the correct Profile role."""
        call_command("create_checker_sessions")
        for username, expected in self.EXPECTED_SESSIONS.items():
            user = User.objects.get(username=username)
            self.assertTrue(
                hasattr(user, "profile"),
                f"User '{username}' has no Profile.",
            )
            self.assertEqual(
                user.profile.role,
                expected["role"],
                f"User '{username}' has role '{user.profile.role}', "
                f"expected '{expected['role']}'.",
            )

    def test_exact_session_keys_exist(self):
        """The exact four session keys exist in the session store."""
        call_command("create_checker_sessions")
        for username, expected in self.EXPECTED_SESSIONS.items():
            session = SessionStore(session_key=expected["session_key"])
            self.assertFalse(
                session.is_empty(),
                f"Session '{expected['session_key']}' for '{username}' is empty.",
            )

    def test_idempotent_no_duplication(self):
        """Running create_checker_sessions twice doesn't duplicate users or sessions."""
        call_command("create_checker_sessions")
        call_command("create_checker_sessions")

        # Exactly 4 users created
        checker_usernames = list(self.EXPECTED_SESSIONS.keys())
        user_count = User.objects.filter(username__in=checker_usernames).count()
        self.assertEqual(user_count, 4, "Expected exactly 4 checker users after two runs.")

        # All sessions still work
        for username, expected in self.EXPECTED_SESSIONS.items():
            session = SessionStore(session_key=expected["session_key"])
            self.assertFalse(session.is_empty())


class CheckerSessionResolutionTest(TestCase):
    """
    Tests that the fixed checker session cookies correctly resolve
    request.user via Django's full middleware stack.

    These tests attach the cookie and make a real HTTP request through
    the test client, letting SessionMiddleware and AuthenticationMiddleware
    resolve the user — no mocking of request.user.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        call_command("create_checker_sessions")

    def _request_with_session(self, session_key):
        """Make a GET to /accounts/whoami/ with the given session cookie."""
        client = Client()
        client.cookies[settings.SESSION_COOKIE_NAME] = session_key
        return client.get("/accounts/whoami/")

    def test_org_7f2a_resolves_to_organizer(self):
        """Cookie session=org_7f2a resolves request.user to 'organizer'."""
        response = self._request_with_session("org_7f2a")
        data = response.json()
        self.assertTrue(data["authenticated"])
        self.assertEqual(data["username"], "organizer")
        self.assertEqual(data["role"], "organizer")

    def test_jdg_a_91bc_resolves_to_judge_a(self):
        """Cookie session=jdg_a_91bc resolves request.user to 'judge_a'."""
        response = self._request_with_session("jdg_a_91bc")
        data = response.json()
        self.assertTrue(data["authenticated"])
        self.assertEqual(data["username"], "judge_a")
        self.assertEqual(data["role"], "judge")

    def test_jdg_b_44de_resolves_to_judge_b(self):
        """Cookie session=jdg_b_44de resolves request.user to 'judge_b'."""
        response = self._request_with_session("jdg_b_44de")
        data = response.json()
        self.assertTrue(data["authenticated"])
        self.assertEqual(data["username"], "judge_b")
        self.assertEqual(data["role"], "judge")

    def test_prt_2e88_resolves_to_participant(self):
        """Cookie session=prt_2e88 resolves request.user to 'participant'."""
        response = self._request_with_session("prt_2e88")
        data = response.json()
        self.assertTrue(data["authenticated"])
        self.assertEqual(data["username"], "participant")
        self.assertEqual(data["role"], "participant")

    def test_invalid_session_does_not_authenticate(self):
        """An unknown session cookie does not authenticate a user."""
        response = self._request_with_session("invalid_session_key_xyz")
        data = response.json()
        self.assertFalse(data["authenticated"])
        self.assertIsNone(data["username"])
        self.assertIsNone(data["role"])

    def test_no_cookie_does_not_authenticate(self):
        """A request with no session cookie is unauthenticated."""
        client = Client()
        response = client.get("/accounts/whoami/")
        data = response.json()
        self.assertFalse(data["authenticated"])
        self.assertIsNone(data["username"])
        self.assertIsNone(data["role"])
