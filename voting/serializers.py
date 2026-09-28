"""
DRF serializers for the voting API.
"""
from rest_framework import serializers


class VoteInputSerializer(serializers.Serializer):
    """Validates the JSON body for POST /api/vote/ and POST /api/vote/link/<token>/"""
    event = serializers.IntegerField()
    project = serializers.IntegerField()


class VoteResponseSerializer(serializers.Serializer):
    """Shapes the 201 response after a successful vote."""
    event = serializers.IntegerField()
    project = serializers.IntegerField()
    vote_id = serializers.IntegerField()


class BallotProjectSerializer(serializers.Serializer):
    """Shapes a single project entry in the ballot response."""
    id = serializers.IntegerField()
    title = serializers.CharField()
    summary = serializers.CharField()
    track = serializers.CharField()


class BallotResponseSerializer(serializers.Serializer):
    """Shapes the 200 response for GET /api/vote/ballot/<event_id>/"""
    event = serializers.IntegerField()
    projects = BallotProjectSerializer(many=True)
