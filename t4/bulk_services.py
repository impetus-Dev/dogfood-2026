"""
Bulk export and import engine for DOGFOOD 2026 (T4-A Person B slice).

Features:
- B1: Bulk JSON export with strict secret scrubbing.
- B2-B6: Bulk JSON import with whole-payload pre-validation, dry-run support,
  all-or-nothing database transactions, and external_id reconciliation.
"""
from datetime import datetime, timezone
import json
import secrets
from typing import Any, Dict, List, Tuple

from django.contrib.auth import get_user_model
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.dateparse import parse_datetime

from accounts.models import Profile
from events.models import Event, Track
from teams.models import Team, TeamMembership
from projects.models import Project

User = get_user_model()

FORBIDDEN_SECRET_KEYS = frozenset([
    "password",
    "password_hash",
    "session",
    "session_key",
    "csrf",
    "csrf_token",
    "csrftoken",
    "token",
    "voting_token",
    "secret",
    "secret_key",
    "private_key",
    "signing_key",
    "seed",
])


def scrub_and_verify_secrets(data: Any, path: str = "") -> None:
    """
    Recursively inspects data to assert that no sensitive key or token
    leaks into exported or processed payloads.
    Raises ValueError if a forbidden key is detected.
    """
    if isinstance(data, dict):
        for k, v in data.items():
            k_lower = str(k).lower()
            if any(forbidden in k_lower for forbidden in FORBIDDEN_SECRET_KEYS):
                # Allowed exception: invite_code is public team metadata, not an auth secret
                if k_lower != "invite_code":
                    raise ValueError(f"Secret leakage detected at key '{path}.{k}'")
            scrub_and_verify_secrets(v, f"{path}.{k}")
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            scrub_and_verify_secrets(item, f"{path}[{idx}]")


def export_bulk_data(event_id: int | None = None) -> Dict[str, Any]:
    """
    Exports hackathon domain data: Events, Tracks, Teams, Safe TeamMemberships, and Projects.
    Ensures absolute secret exclusion: no passwords, sessions, CSRF, or private keys.
    """
    event_qs = Event.objects.all().order_by("pk")
    if event_id is not None:
        event_qs = event_qs.filter(pk=event_id)

    events_list = []
    for ev in event_qs:
        events_list.append({
            "id": ev.pk,
            "external_id": ev.external_id or f"evt_{ev.pk}",
            "name": ev.name,
            "submissions_close": ev.submissions_close.isoformat() if ev.submissions_close else None,
            "voting_close": ev.voting_close.isoformat() if ev.voting_close else None,
            "voting_mode": ev.voting_mode,
        })

    track_qs = Track.objects.select_related("event").all().order_by("pk")
    if event_id is not None:
        track_qs = track_qs.filter(event_id=event_id)

    tracks_list = []
    for trk in track_qs:
        tracks_list.append({
            "id": trk.pk,
            "external_id": trk.external_id or f"trk_{trk.pk}",
            "event_id": trk.event_id,
            "event_external_id": trk.event.external_id or f"evt_{trk.event.pk}",
            "name": trk.name,
        })

    team_qs = Team.objects.select_related("event").prefetch_related("memberships__user__profile").all().order_by("pk")
    if event_id is not None:
        team_qs = team_qs.filter(event_id=event_id)

    teams_list = []
    for tm in team_qs:
        members_data = []
        for mem in tm.memberships.all():
            user_profile = getattr(mem.user, "profile", None)
            members_data.append({
                "username": mem.user.username,
                "role": user_profile.role if user_profile else "participant",
            })

        teams_list.append({
            "id": tm.pk,
            "external_id": tm.external_id or f"tm_{tm.pk}",
            "event_id": tm.event_id,
            "event_external_id": tm.event.external_id or f"evt_{tm.event.pk}",
            "name": tm.name,
            "members": members_data,
        })

    proj_qs = Project.objects.select_related("team__event", "track__event").all().order_by("pk")
    if event_id is not None:
        proj_qs = proj_qs.filter(team__event_id=event_id)

    projects_list = []
    for prj in proj_qs:
        projects_list.append({
            "id": prj.pk,
            "external_id": prj.external_id or f"prj_{prj.pk}",
            "team_id": prj.team_id,
            "team_external_id": prj.team.external_id or f"tm_{prj.team.pk}",
            "track_id": prj.track_id,
            "track_external_id": prj.track.external_id or f"trk_{prj.track.pk}",
            "title": prj.title,
            "summary": prj.summary,
            "repo_url": prj.repo_url,
            "status": prj.status,
            "submitted_at": prj.submitted_at.isoformat() if prj.submitted_at else None,
        })

    payload = {
        "event": events_list[0] if len(events_list) == 1 else None,
        "events": events_list,
        "tracks": tracks_list,
        "teams": teams_list,
        "projects": projects_list,
    }

    # Strict secret scrubbing and verification
    scrub_and_verify_secrets(payload)
    return payload


def _parse_datetime_field(val: Any) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        dt = parse_datetime(val)
        if dt is None:
            # Fall back to datetime.fromisoformat
            try:
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            except ValueError:
                return None
        return dt
    return None


def validate_bulk_payload(payload: Any) -> Tuple[List[str], Dict[str, Any]]:
    """
    Whole-payload pre-validation.
    Validates all entities, relationships, foreign keys, and fields before
    any database writes occur.
    Returns (errors_list, parsed_entities_dict).
    """
    errors: List[str] = []
    parsed: Dict[str, Any] = {
        "events": [],
        "tracks": [],
        "teams": [],
        "projects": [],
    }

    if not isinstance(payload, dict):
        return ["Payload must be a JSON object."], parsed

    # Extract events
    raw_events = payload.get("events")
    if raw_events is None and "event" in payload and isinstance(payload["event"], dict):
        raw_events = [payload["event"]]
    elif raw_events is None:
        raw_events = []

    if not isinstance(raw_events, list):
        errors.append("'events' must be a list.")
        raw_events = []

    # Extract tracks, teams, projects
    raw_tracks = payload.get("tracks", [])
    if not isinstance(raw_tracks, list):
        errors.append("'tracks' must be a list.")
        raw_tracks = []

    raw_teams = payload.get("teams", [])
    if not isinstance(raw_teams, list):
        errors.append("'teams' must be a list.")
        raw_teams = []

    raw_projects = payload.get("projects", [])
    if not isinstance(raw_projects, list):
        errors.append("'projects' must be a list.")
        raw_projects = []

    # 1. Validate Events
    event_keys = set()
    event_ext_ids = set()
    for idx, ev in enumerate(raw_events):
        if not isinstance(ev, dict):
            errors.append(f"Event at index {idx} must be an object.")
            continue

        name = ev.get("name")
        if not name or not str(name).strip():
            errors.append(f"Event at index {idx} missing required 'name'.")

        sub_close_raw = ev.get("submissions_close")
        if not sub_close_raw:
            errors.append(f"Event '{name or idx}' missing required 'submissions_close'.")
        else:
            dt = _parse_datetime_field(sub_close_raw)
            if dt is None:
                errors.append(f"Event '{name or idx}' invalid 'submissions_close' datetime: {sub_close_raw}")

        ext_id = ev.get("external_id") or (ev.get("id") if isinstance(ev.get("id"), str) else None)
        if ext_id:
            if ext_id in event_ext_ids:
                errors.append(f"Duplicate event external_id: '{ext_id}'.")
            event_ext_ids.add(ext_id)
            event_keys.add(ext_id)

        pk_id = ev.get("id")
        if isinstance(pk_id, int):
            event_keys.add(pk_id)

        parsed["events"].append(ev)

    # If payload defines no events, check if DB has events
    db_events = {e.pk: e for e in Event.objects.all()}
    db_event_ext_ids = {e.external_id: e for e in db_events.values() if e.external_id}
    single_event_available = len(parsed["events"]) == 1 or len(db_events) == 1

    # 2. Validate Tracks
    track_ext_ids = set()
    for idx, trk in enumerate(raw_tracks):
        if not isinstance(trk, dict):
            errors.append(f"Track at index {idx} must be an object.")
            continue

        name = trk.get("name")
        if not name or not str(name).strip():
            errors.append(f"Track at index {idx} missing required 'name'.")

        ext_id = trk.get("external_id") or (trk.get("id") if isinstance(trk.get("id"), str) else None)
        if ext_id:
            if ext_id in track_ext_ids:
                errors.append(f"Duplicate track external_id: '{ext_id}'.")
            track_ext_ids.add(ext_id)

        # Resolve event reference
        ev_ref = trk.get("event_external_id") or trk.get("event_id") or trk.get("event")
        if not ev_ref and not single_event_available:
            errors.append(f"Track '{name or idx}' must specify an event reference.")
        elif ev_ref:
            if ev_ref not in event_keys and ev_ref not in db_events and ev_ref not in db_event_ext_ids:
                errors.append(f"Track '{name or idx}' references non-existent event '{ev_ref}'.")

        parsed["tracks"].append(trk)

    # 3. Validate Teams
    team_ext_ids = set()
    for idx, tm in enumerate(raw_teams):
        if not isinstance(tm, dict):
            errors.append(f"Team at index {idx} must be an object.")
            continue

        name = tm.get("name")
        if not name or not str(name).strip():
            errors.append(f"Team at index {idx} missing required 'name'.")

        ext_id = tm.get("external_id") or (tm.get("id") if isinstance(tm.get("id"), str) else None)
        if ext_id:
            if ext_id in team_ext_ids:
                errors.append(f"Duplicate team external_id: '{ext_id}'.")
            team_ext_ids.add(ext_id)

        ev_ref = tm.get("event_external_id") or tm.get("event_id") or tm.get("event")
        if not ev_ref and not single_event_available:
            errors.append(f"Team '{name or idx}' must specify an event reference.")
        elif ev_ref:
            if ev_ref not in event_keys and ev_ref not in db_events and ev_ref not in db_event_ext_ids:
                errors.append(f"Team '{name or idx}' references non-existent event '{ev_ref}'.")

        # Validate members format if provided
        members = tm.get("members", [])
        if members and not isinstance(members, list):
            errors.append(f"Team '{name or idx}' 'members' must be a list.")

        parsed["teams"].append(tm)

    # 4. Validate Projects
    url_validator = URLValidator()
    project_ext_ids = set()
    db_tracks_by_ext = {t.external_id: t for t in Track.objects.all() if t.external_id}
    db_tracks_by_id = {t.pk: t for t in Track.objects.all()}
    db_teams_by_ext = {t.external_id: t for t in Team.objects.all() if t.external_id}
    db_teams_by_id = {t.pk: t for t in Team.objects.all()}

    for idx, prj in enumerate(raw_projects):
        if not isinstance(prj, dict):
            errors.append(f"Project at index {idx} must be an object.")
            continue

        title = prj.get("title")
        if not title or not str(title).strip():
            errors.append(f"Project at index {idx} missing required 'title'.")

        summary = prj.get("summary")
        if not summary or not str(summary).strip():
            errors.append(f"Project '{title or idx}' missing required 'summary'.")

        repo_url = prj.get("repo_url")
        if not repo_url or not str(repo_url).strip():
            errors.append(f"Project '{title or idx}' missing required 'repo_url'.")
        else:
            try:
                url_validator(repo_url)
            except ValidationError:
                errors.append(f"Project '{title or idx}' has invalid 'repo_url': {repo_url}")

        ext_id = prj.get("external_id") or (prj.get("id") if isinstance(prj.get("id"), str) else None)
        if ext_id:
            if ext_id in project_ext_ids:
                errors.append(f"Duplicate project external_id: '{ext_id}'.")
            project_ext_ids.add(ext_id)

        # Team reference
        tm_ref = prj.get("team_external_id") or prj.get("team_id") or prj.get("team")
        if not tm_ref:
            errors.append(f"Project '{title or idx}' missing required 'team' reference.")
        elif tm_ref not in team_ext_ids and tm_ref not in db_teams_by_ext and tm_ref not in db_teams_by_id:
            errors.append(f"Project '{title or idx}' references non-existent team '{tm_ref}'.")

        # Track reference
        trk_ref = prj.get("track_external_id") or prj.get("track_id") or prj.get("track")
        if not trk_ref:
            errors.append(f"Project '{title or idx}' missing required 'track' reference.")
        elif trk_ref not in track_ext_ids and trk_ref not in db_tracks_by_ext and trk_ref not in db_tracks_by_id:
            errors.append(f"Project '{title or idx}' references non-existent track '{trk_ref}'.")

        parsed["projects"].append(prj)

    return errors, parsed


def import_bulk_data(payload: Any, dry_run: bool = False) -> Dict[str, Any]:
    """
    Executes bulk data import with strict all-or-nothing atomicity.
    If dry_run=True, pre-validates and calculates create/update counts with ZERO database writes.
    If dry_run=False, wraps the execution in transaction.atomic() to ensure total rollback on error.
    """
    # 1. Whole-payload pre-validation
    errors, parsed = validate_bulk_payload(payload)
    if errors:
        return {
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": errors,
        }

    # If dry-run: compute prospective counts without writing anything
    if dry_run:
        created = 0
        updated = 0
        skipped = 0

        # Check prospective events
        for ev in parsed["events"]:
            ext_id = ev.get("external_id") or (ev.get("id") if isinstance(ev.get("id"), str) else None)
            pk_id = ev.get("id") if isinstance(ev.get("id"), int) else None
            if (ext_id and Event.objects.filter(external_id=ext_id).exists()) or (pk_id and Event.objects.filter(pk=pk_id).exists()):
                updated += 1
            else:
                created += 1

        # Check prospective tracks
        for trk in parsed["tracks"]:
            ext_id = trk.get("external_id") or (trk.get("id") if isinstance(trk.get("id"), str) else None)
            pk_id = trk.get("id") if isinstance(trk.get("id"), int) else None
            if (ext_id and Track.objects.filter(external_id=ext_id).exists()) or (pk_id and Track.objects.filter(pk=pk_id).exists()):
                updated += 1
            else:
                created += 1

        # Check prospective teams
        for tm in parsed["teams"]:
            ext_id = tm.get("external_id") or (tm.get("id") if isinstance(tm.get("id"), str) else None)
            pk_id = tm.get("id") if isinstance(tm.get("id"), int) else None
            if (ext_id and Team.objects.filter(external_id=ext_id).exists()) or (pk_id and Team.objects.filter(pk=pk_id).exists()):
                updated += 1
            else:
                created += 1

        # Check prospective projects
        for prj in parsed["projects"]:
            ext_id = prj.get("external_id") or (prj.get("id") if isinstance(prj.get("id"), str) else None)
            pk_id = prj.get("id") if isinstance(prj.get("id"), int) else None
            if (ext_id and Project.objects.filter(external_id=ext_id).exists()) or (pk_id and Project.objects.filter(pk=pk_id).exists()):
                updated += 1
            else:
                created += 1

        return {
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "errors": [],
        }

    # 2. Real import execution wrapped in transaction.atomic()
    created = 0
    updated = 0
    skipped = 0

    try:
        with transaction.atomic():
            # In-memory lookup caches for resolving foreign keys
            event_map: Dict[Any, Event] = {}
            track_map: Dict[Any, Track] = {}
            team_map: Dict[Any, Team] = {}

            # Seed caches with existing DB records
            for ev in Event.objects.all():
                event_map[ev.pk] = ev
                if ev.external_id:
                    event_map[ev.external_id] = ev

            # Process Events
            for ev_data in parsed["events"]:
                ext_id = ev_data.get("external_id") or (ev_data.get("id") if isinstance(ev_data.get("id"), str) else None)
                pk_id = ev_data.get("id") if isinstance(ev_data.get("id"), int) else None
                name = ev_data["name"]
                sub_close = _parse_datetime_field(ev_data["submissions_close"])
                voting_close = _parse_datetime_field(ev_data.get("voting_close"))
                voting_mode = ev_data.get("voting_mode", "authenticated")

                event_instance = None
                if ext_id and ext_id in event_map:
                    event_instance = event_map[ext_id]
                elif pk_id and pk_id in event_map:
                    event_instance = event_map[pk_id]

                if event_instance:
                    event_instance.name = name
                    event_instance.submissions_close = sub_close
                    if voting_close is not None:
                        event_instance.voting_close = voting_close
                    if voting_mode:
                        event_instance.voting_mode = voting_mode
                    event_instance.save()
                    updated += 1
                else:
                    event_instance = Event.objects.create(
                        name=name,
                        external_id=ext_id,
                        submissions_close=sub_close,
                        voting_close=voting_close,
                        voting_mode=voting_mode,
                    )
                    created += 1

                event_map[event_instance.pk] = event_instance
                if event_instance.external_id:
                    event_map[event_instance.external_id] = event_instance

            # Determine fallback single event
            single_event = None
            if len(event_map) == 1:
                single_event = list(event_map.values())[0]
            elif parsed["events"]:
                single_event = event_map.get(parsed["events"][0].get("external_id")) or event_map.get(parsed["events"][0].get("id"))

            # Populate track cache
            for trk in Track.objects.all():
                track_map[trk.pk] = trk
                if trk.external_id:
                    track_map[trk.external_id] = trk

            # Process Tracks
            for trk_data in parsed["tracks"]:
                ext_id = trk_data.get("external_id") or (trk_data.get("id") if isinstance(trk_data.get("id"), str) else None)
                pk_id = trk_data.get("id") if isinstance(trk_data.get("id"), int) else None
                name = trk_data["name"]
                ev_ref = trk_data.get("event_external_id") or trk_data.get("event_id") or trk_data.get("event")
                ev_obj = event_map.get(ev_ref) or single_event

                if not ev_obj:
                    raise ValidationError(f"Cannot resolve event for track '{name}'")

                track_instance = None
                if ext_id and ext_id in track_map:
                    track_instance = track_map[ext_id]
                elif pk_id and pk_id in track_map:
                    track_instance = track_map[pk_id]

                if track_instance:
                    track_instance.name = name
                    track_instance.event = ev_obj
                    track_instance.save()
                    updated += 1
                else:
                    track_instance = Track.objects.create(
                        name=name,
                        external_id=ext_id,
                        event=ev_obj,
                    )
                    created += 1

                track_map[track_instance.pk] = track_instance
                if track_instance.external_id:
                    track_map[track_instance.external_id] = track_instance

            # Populate team cache
            for tm in Team.objects.all():
                team_map[tm.pk] = tm
                if tm.external_id:
                    team_map[tm.external_id] = tm

            # Process Teams
            for tm_data in parsed["teams"]:
                ext_id = tm_data.get("external_id") or (tm_data.get("id") if isinstance(tm_data.get("id"), str) else None)
                pk_id = tm_data.get("id") if isinstance(tm_data.get("id"), int) else None
                name = tm_data["name"]
                ev_ref = tm_data.get("event_external_id") or tm_data.get("event_id") or tm_data.get("event")
                ev_obj = event_map.get(ev_ref) or single_event

                if not ev_obj:
                    raise ValidationError(f"Cannot resolve event for team '{name}'")

                team_instance = None
                if ext_id and ext_id in team_map:
                    team_instance = team_map[ext_id]
                elif pk_id and pk_id in team_map:
                    team_instance = team_map[pk_id]

                if team_instance:
                    team_instance.name = name
                    team_instance.event = ev_obj
                    team_instance.save()
                    updated += 1
                else:
                    invite_code = secrets.token_hex(16)
                    team_instance = Team.objects.create(
                        name=name,
                        external_id=ext_id,
                        event=ev_obj,
                        invite_code=invite_code,
                    )
                    created += 1

                team_map[team_instance.pk] = team_instance
                if team_instance.external_id:
                    team_map[team_instance.external_id] = team_instance

                # Process safe team memberships
                members = tm_data.get("members", [])
                for m in members:
                    username = m if isinstance(m, str) else m.get("username")
                    if username:
                        user, user_created = User.objects.get_or_create(username=username)
                        if user_created:
                            user.set_unusable_password()
                            user.save()
                        Profile.objects.get_or_create(user=user, defaults={"role": "participant"})
                        TeamMembership.objects.get_or_create(team=team_instance, user=user)

            # Populate project cache
            project_map = {}
            for prj in Project.objects.all():
                project_map[prj.pk] = prj
                if prj.external_id:
                    project_map[prj.external_id] = prj

            # Process Projects
            for prj_data in parsed["projects"]:
                ext_id = prj_data.get("external_id") or (prj_data.get("id") if isinstance(prj_data.get("id"), str) else None)
                pk_id = prj_data.get("id") if isinstance(prj_data.get("id"), int) else None
                title = prj_data["title"]
                summary = prj_data["summary"]
                repo_url = prj_data["repo_url"]
                status = prj_data.get("status", "submitted")
                sub_at = _parse_datetime_field(prj_data.get("submitted_at")) or datetime.now(timezone.utc)

                tm_ref = prj_data.get("team_external_id") or prj_data.get("team_id") or prj_data.get("team")
                trk_ref = prj_data.get("track_external_id") or prj_data.get("track_id") or prj_data.get("track")

                tm_obj = team_map.get(tm_ref)
                trk_obj = track_map.get(trk_ref)

                if not tm_obj or not trk_obj:
                    raise ValidationError(f"Cannot resolve team or track for project '{title}'")

                if tm_obj.event_id != trk_obj.event_id:
                    raise ValidationError(f"Project '{title}' team and track belong to different events")

                project_instance = None
                if ext_id and ext_id in project_map:
                    project_instance = project_map[ext_id]
                elif pk_id and pk_id in project_map:
                    project_instance = project_map[pk_id]

                if project_instance:
                    project_instance.title = title
                    project_instance.summary = summary
                    project_instance.repo_url = repo_url
                    project_instance.status = status
                    project_instance.submitted_at = sub_at
                    project_instance.team = tm_obj
                    project_instance.track = trk_obj
                    project_instance.save()
                    updated += 1
                else:
                    project_instance = Project.objects.create(
                        title=title,
                        summary=summary,
                        repo_url=repo_url,
                        status=status,
                        submitted_at=sub_at,
                        team=tm_obj,
                        track=trk_obj,
                        external_id=ext_id,
                    )
                    created += 1

                project_map[project_instance.pk] = project_instance
                if project_instance.external_id:
                    project_map[project_instance.external_id] = project_instance

        return {
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "errors": [],
        }

    except Exception as e:
        # Atomic block automatically rolled back all DB operations
        return {
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [str(e)],
        }
