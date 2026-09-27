from django.test import TestCase
from django.utils import timezone
from .models import Event, Track


class EventsModelTest(TestCase):
    def test_event_and_track_creation(self):
        now = timezone.now()
        event = Event.objects.create(
            name="Hackathon 2026",
            submissions_close=now,
            voting_mode="authenticated"
        )
        track = Track.objects.create(event=event, name="AI / ML")
        self.assertEqual(event.name, "Hackathon 2026")
        self.assertEqual(track.event, event)
        self.assertEqual(str(event), "Hackathon 2026")
        self.assertEqual(str(track), "Hackathon 2026 - AI / ML")
