from django.db import models
from django.contrib.auth.models import User


class Profile(models.Model):
    ROLE_CHOICES = [
        ("visitor", "Visitor"),
        ("participant", "Participant"),
        ("judge", "Judge"),
        ("organizer", "Organizer"),
        ("admin", "Admin"),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default="participant")

    def __str__(self):
        return f"{self.user.username} ({self.role})"
