import os
import importlib
from django.test import TestCase
from django.contrib.auth.models import User
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from .models import Profile


class AccountsModelTest(TestCase):
    def test_session_cookie_name(self):
        self.assertEqual(settings.SESSION_COOKIE_NAME, "session")

    def test_secret_key_loaded(self):
        self.assertTrue(bool(settings.SECRET_KEY))

    def test_missing_secret_key_raises_improperly_configured(self):
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

    def test_profile_creation(self):
        user = User.objects.create_user(username="testuser", password="password123")
        profile = Profile.objects.create(user=user, role="participant")
        self.assertEqual(profile.role, "participant")
        self.assertEqual(str(profile), "testuser (participant)")
