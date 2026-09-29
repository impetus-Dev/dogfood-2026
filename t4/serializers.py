import base64
from django.contrib.auth import get_user_model
from rest_framework import serializers

from events.models import Event
from judging.models import JudgeAssignment, Score
from projects.models import Project
from teams.models import TeamMembership
from t4.models import Certificate, JudgeRecord

User = get_user_model()


class CreateJudgeRecordSerializer(serializers.Serializer):
    event = serializers.IntegerField(required=True)
    judge = serializers.IntegerField(required=True)

    def validate_event(self, value):
        try:
            return Event.objects.get(pk=value)
        except Event.DoesNotExist:
            raise serializers.ValidationError("Event not found.")

    def validate_judge(self, value):
        try:
            user = User.objects.get(pk=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("Judge user not found.")

        profile = getattr(user, "profile", None)
        if not profile or profile.role != "judge":
            raise serializers.ValidationError("User does not have the 'judge' role.")
        return user

    def validate(self, attrs):
        event = attrs["event"]
        judge = attrs["judge"]

        has_assignment = JudgeAssignment.objects.filter(judge=judge, project__team__event=event).exists()
        has_score = Score.objects.filter(judge=judge, project__team__event=event).exists()

        if not has_assignment and not has_score:
            raise serializers.ValidationError(
                "No judging participation found for this judge in this event."
            )

        return attrs


class JudgeRecordResponseSerializer(serializers.ModelSerializer):
    judge = serializers.CharField(source="judge.username")
    event = serializers.IntegerField(source="event.id")
    algorithm = serializers.CharField(default="Ed25519")
    signature = serializers.SerializerMethodField()

    class Meta:
        model = JudgeRecord
        fields = ["id", "judge", "event", "algorithm", "payload", "signature", "created_at"]

    def get_signature(self, obj):
        return base64.b64encode(bytes(obj.signature)).decode("ascii")


class CreateCertificateSerializer(serializers.Serializer):
    event = serializers.IntegerField(required=True)
    context_type = serializers.ChoiceField(choices=["participant", "judge"], required=True)
    user = serializers.IntegerField(required=True)
    project = serializers.IntegerField(required=False, allow_null=True)

    def validate_event(self, value):
        try:
            return Event.objects.get(pk=value)
        except Event.DoesNotExist:
            raise serializers.ValidationError("Event not found.")

    def validate_user(self, value):
        try:
            return User.objects.get(pk=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found.")

    def validate_project(self, value):
        if value is None:
            return None
        try:
            return Project.objects.get(pk=value)
        except Project.DoesNotExist:
            raise serializers.ValidationError("Project not found.")

    def validate(self, attrs):
        event = attrs["event"]
        user = attrs["user"]
        context_type = attrs["context_type"]
        project = attrs.get("project")

        if context_type == "participant":
            if project:
                if project.team.event_id != event.pk:
                    raise serializers.ValidationError("Project does not belong to this event.")
                if not TeamMembership.objects.filter(team=project.team, user=user).exists():
                    raise serializers.ValidationError("User is not a member of the project's team.")
            else:
                if not TeamMembership.objects.filter(team__event=event, user=user).exists():
                    raise serializers.ValidationError("User is not a member of any team in this event.")

        elif context_type == "judge":
            profile = getattr(user, "profile", None)
            if not profile or profile.role != "judge":
                raise serializers.ValidationError("User does not have the 'judge' role.")

            if project:
                if project.team.event_id != event.pk:
                    raise serializers.ValidationError("Project does not belong to this event.")
                has_evaluated = (
                    JudgeAssignment.objects.filter(judge=user, project=project).exists()
                    or Score.objects.filter(judge=user, project=project).exists()
                )
                if not has_evaluated:
                    raise serializers.ValidationError(
                        "Inappropriate project usage: judge did not evaluate this project."
                    )

            has_assignment = JudgeAssignment.objects.filter(judge=user, project__team__event=event).exists()
            has_score = Score.objects.filter(judge=user, project__team__event=event).exists()
            if not has_assignment and not has_score:
                raise serializers.ValidationError(
                    "No judging participation found for this judge in this event."
                )

        return attrs


class CertificateResponseSerializer(serializers.ModelSerializer):
    event = serializers.IntegerField(source="event.id")

    class Meta:
        model = Certificate
        fields = ["id", "recipient_name", "event", "role_or_project", "issued_at"]
