from django.conf import settings
from django.db import models


class Profile(models.Model):
    ROLE_CHOICES = [
        ("visitor", "Visitor"),
        ("participant", "Participant"),
        ("judge", "Judge"),
        ("organizer", "Organizer"),
        ("admin", "Admin"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="visitor")

    def __str__(self):
        return f"{self.user} ({self.role})"
