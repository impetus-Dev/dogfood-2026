from django.test import TestCase
from django.contrib.auth.models import User
from django.conf import settings
from .models import Profile


class AccountsModelTest(TestCase):
    def test_session_cookie_name(self):
        self.assertEqual(settings.SESSION_COOKIE_NAME, "session")

    def test_profile_creation(self):
        user = User.objects.create_user(username="testuser", password="password123")
        profile = Profile.objects.create(user=user, role="participant")
        self.assertEqual(profile.role, "participant")
        self.assertEqual(str(profile), "testuser (participant)")
