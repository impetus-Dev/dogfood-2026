from django.db import models


class Event(models.Model):
    VOTING_MODE_CHOICES = [
        ("authenticated", "Authenticated"),
        ("link", "Link-based"),
    ]

    name = models.CharField(max_length=255)
    external_id = models.CharField(max_length=64, blank=True, null=True, unique=True)
    submissions_close = models.DateTimeField()
    voting_close = models.DateTimeField(null=True, blank=True)
    voting_mode = models.CharField(
        max_length=16,
        choices=VOTING_MODE_CHOICES,
        default="authenticated",
    )

    def __str__(self):
        return self.name


class Track(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="tracks")
    name = models.CharField(max_length=255)
    external_id = models.CharField(max_length=64, blank=True, null=True, unique=True)

    def __str__(self):
        return f"{self.event.name} - {self.name}"
