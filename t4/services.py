import base64
import binascii
import json
import os
from django.conf import settings
from django.core.exceptions import ValidationError
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

from accounts.models import Profile
from events.models import Event
from judging.models import JudgeAssignment, Score
from projects.models import Project
from teams.models import Team, TeamMembership
from t4.models import Certificate, JudgeRecord


def get_signing_key_path() -> str:
    """Return the filesystem path for the persisted Ed25519 signing key."""
    return getattr(
        settings,
        "T4_SIGNING_KEY_PATH",
        os.environ.get("T4_SIGNING_KEY_PATH", "/keys/t4_signing_key"),
    )


def init_signing_key(path: str | None = None) -> bool:
    """
    Initialize the Ed25519 signing key on disk.
    If the key file does not exist:
      1. Generates an Ed25519 private key
      2. Extracts the raw 32-byte private key seed
      3. Base64 encodes the 32-byte seed
      4. Writes it to path with mode 0600
    If the key file already exists:
      1. Loads it, base64 decodes it, requires exactly 32 decoded bytes
      2. Fails safely on corruption without silently generating a new key
    """
    key_path = path or get_signing_key_path()

    if os.path.exists(key_path):
        with open(key_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        try:
            raw_bytes = base64.b64decode(content)
        except (binascii.Error, ValueError) as e:
            raise ValueError(f"Corrupt signing key at {key_path}: base64 decode failed: {e}")
        if len(raw_bytes) != 32:
            raise ValueError(
                f"Corrupt signing key at {key_path}: expected 32 decoded bytes, got {len(raw_bytes)}"
            )
        # Validate that Ed25519 accepts the bytes
        Ed25519PrivateKey.from_private_bytes(raw_bytes)
        return True

    # Generate new key
    dir_name = os.path.dirname(key_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    priv_key = Ed25519PrivateKey.generate()
    raw_seed = priv_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    b64_seed = base64.b64encode(raw_seed).decode("ascii")

    # Write securely with mode 0600
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    mode = 0o600
    fd = os.open(key_path, flags, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(b64_seed)

    return True


def get_signing_private_key(path: str | None = None) -> Ed25519PrivateKey:
    """Load the persisted Ed25519 private key."""
    key_path = path or get_signing_key_path()
    if not os.path.exists(key_path):
        # Auto-initialize if running in test environment and directory is writable
        init_signing_key(key_path)

    with open(key_path, "r", encoding="utf-8") as f:
        content = f.read().strip()
    try:
        raw_bytes = base64.b64decode(content)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"Corrupt signing key at {key_path}: base64 decode failed: {e}")

    if len(raw_bytes) != 32:
        raise ValueError(
            f"Corrupt signing key at {key_path}: expected 32 decoded bytes, got {len(raw_bytes)}"
        )

    return Ed25519PrivateKey.from_private_bytes(raw_bytes)


def get_public_key(path: str | None = None) -> Ed25519PublicKey:
    """Get the Ed25519 public key derived from the persisted private key."""
    priv = get_signing_private_key(path)
    return priv.public_key()


def get_public_key_base64(public_key: Ed25519PublicKey | None = None, path: str | None = None) -> str:
    """Return the raw 32-byte public key as a base64 encoded string."""
    pub = public_key or get_public_key(path)
    raw = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")


def canonicalize_payload(payload: dict) -> bytes:
    """
    Produce deterministic, canonical UTF-8 bytes for a JSON payload dictionary.
    Keys are sorted, separators are without extra whitespace.
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sign_payload(payload: dict, path: str | None = None) -> bytes:
    """Sign a payload dictionary using the persisted Ed25519 private key."""
    canonical_bytes = canonicalize_payload(payload)
    priv = get_signing_private_key(path)
    return priv.sign(canonical_bytes)


def verify_payload_signature(
    payload: dict,
    signature: bytes,
    public_key: Ed25519PublicKey | None = None,
    path: str | None = None,
) -> bool:
    """
    Verify the signature over a payload dictionary using the Ed25519 public key.
    Returns True if valid, False if InvalidSignature.
    Key-loading and canonicalization errors propagate normally.
    """
    canonical_bytes = canonicalize_payload(payload)
    pub = public_key if public_key is not None else get_public_key(path)
    try:
        pub.verify(signature, canonical_bytes)
        return True
    except InvalidSignature:
        return False


def generate_judge_record(judge, event, path: str | None = None) -> JudgeRecord:
    """
    Generate a signed judge participation record for a judge in an event.
    Validates judge role and verifies real judging participation.
    """
    profile = getattr(judge, "profile", None)
    if not profile or profile.role != "judge":
        raise ValidationError("Judge must have a profile with role 'judge'.")

    # Real judging participation evidence from T2 models
    assigned_project_ids = sorted(list(set(
        JudgeAssignment.objects.filter(
            judge=judge, project__team__event=event
        ).values_list("project_id", flat=True)
    )))
    scored_project_ids = sorted(list(set(
        Score.objects.filter(
            judge=judge, project__team__event=event
        ).values_list("project_id", flat=True)
    )))

    if not assigned_project_ids and not scored_project_ids:
        raise ValidationError("No judging participation found for this judge in this event.")

    payload = {
        "schema_version": 1,
        "record_type": "judge_participation",
        "judge_id": judge.pk,
        "event_id": event.pk,
        "event_name": event.name,
        "participation": {
            "assignment_count": len(assigned_project_ids),
            "scored_project_count": len(scored_project_ids),
            "assigned_project_ids": assigned_project_ids,
            "scored_project_ids": scored_project_ids,
        },
    }

    sig = sign_payload(payload, path=path)
    return JudgeRecord.objects.create(
        judge=judge,
        event=event,
        payload=payload,
        signature=sig,
    )


def generate_certificate(
    event: Event,
    user,
    project: Project | None = None,
    context_type: str = "participant",
) -> Certificate:
    """
    Generate a certificate for a user in an event.
    Derives recipient_name and role_or_project server-side from verified relationships.
    """
    if not user:
        raise ValidationError("User is required.")

    if context_type not in ("participant", "judge"):
        raise ValidationError("Context type must be 'participant' or 'judge'.")

    full_name = f"{user.first_name} {user.last_name}".strip()
    recipient_name = full_name if full_name else user.username

    if context_type == "participant":
        if project:
            if project.team.event_id != event.pk:
                raise ValidationError("Project does not belong to this event.")
            if not TeamMembership.objects.filter(team=project.team, user=user).exists():
                raise ValidationError("User is not a member of the project's team.")
            role_or_project = f"Participant - {project.title}"
        else:
            memberships = TeamMembership.objects.filter(team__event=event, user=user)
            if not memberships.exists():
                raise ValidationError("User is not a member of any team in this event.")
            team = memberships.first().team
            role_or_project = f"Participant - {team.name}"

    elif context_type == "judge":
        profile = getattr(user, "profile", None)
        if not profile or profile.role != "judge":
            raise ValidationError("User must have the 'judge' role.")

        if project:
            if project.team.event_id != event.pk:
                raise ValidationError("Project does not belong to this event.")
            has_evaluated = (
                JudgeAssignment.objects.filter(judge=user, project=project).exists()
                or Score.objects.filter(judge=user, project=project).exists()
            )
            if not has_evaluated:
                raise ValidationError("Inappropriate project usage: judge did not evaluate this project.")
            role_or_project = f"Judge - {project.title}"
        else:
            has_assignment = JudgeAssignment.objects.filter(judge=user, project__team__event=event).exists()
            has_score = Score.objects.filter(judge=user, project__team__event=event).exists()
            if not (has_assignment or has_score):
                raise ValidationError("No judging participation found for this judge in this event.")
            role_or_project = "Judge - Participation"

    return Certificate.objects.create(
        recipient_name=recipient_name,
        event=event,
        role_or_project=role_or_project,
    )
