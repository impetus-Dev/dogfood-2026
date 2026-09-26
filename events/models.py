from django.db import models


class Event(models.Model):
    name = models.CharField(max_length=255)
    submissions_close = models.DateTimeField(null=True, blank=True)
    voting_close = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.name


class Track(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="tracks")
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name
