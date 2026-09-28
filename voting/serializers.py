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


class CommentSerializer(serializers.ModelSerializer):
    """Serializer for project comments."""
    author_name = serializers.CharField(max_length=255, trim_whitespace=True)
    text = serializers.CharField(max_length=5000, trim_whitespace=True)

    class Meta:
        from voting.models import Comment
        model = Comment
        fields = ["id", "project", "author_name", "text", "created_at"]
        read_only_fields = ["id", "project", "created_at"]

    def validate_author_name(self, value):
        val = value.strip()
        if not val:
            raise serializers.ValidationError("author_name cannot be blank.")
        return val

    def validate_text(self, value):
        val = value.strip()
        if not val:
            raise serializers.ValidationError("text cannot be blank.")
        return val
