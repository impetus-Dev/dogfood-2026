from io import StringIO
from django.test import TestCase
from django.core.management import call_command


class CoreCommandTest(TestCase):
    def test_seed_fixtures_command(self):
        out = StringIO()
        call_command("seed_fixtures", stdout=out)
        output = out.getvalue()
        self.assertIn("seed_fixtures", output)
